from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..audit.service import get_latest_audit_receipt, serialize_audit_summary
from ..sessions.constants import SessionState
from ..sessions.models import Session as SessionModel
from ..workflow import repository
from ..workflow.service import _build_completion_values
from .graph import build_generalized_verification_graph
from .policies import load_agent_runtime_policy
from .sanitization import sanitize_workspace_payload
from .schemas import (
    FinalVerdict,
    WorkspaceAction,
    WorkspaceAuditEntry,
    WorkspaceDocument,
    WorkspacePayload,
    WorkspaceSummary,
)


LOGGER = logging.getLogger(__name__)

HUMAN_FINAL_WORKSPACE_STATES = {
    SessionState.HUMAN_APPROVED,
    SessionState.HUMAN_REJECTED,
    SessionState.MANUAL_REVIEW_REQUIRED,
}

WORKSPACE_PRIVACY_METADATA = {
    "raw_workspace_text_persisted": False,
    "raw_ocr_text_persisted": False,
    "raw_gemini_output_persisted": False,
    "raw_provider_payloads_persisted": False,
    "raw_reviewer_note_persisted": False,
    "reviewer_note_hash_only": True,
    "source_pdf_retained_until_cleanup": True,
    "raw_text_persisted": False,
    "pii_persisted": False,
    "reviewer_note_persisted": False,
}


def run_generalized_verification_session(
    db,
    session: SessionModel,
    *,
    reviewer_ref: str,
) -> WorkspacePayload:
    if not session.file_path:
        raise ValueError("Upload a PDF before verification")

    file_path = Path(session.file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Document not found for session {session.id}")

    repository.transition_state(
        db,
        session.id,
        SessionState.VERIFYING,
        extra_values={
            "verify_started_at": datetime.utcnow(),
            "worker_phase": "GENERALIZED_PIPELINE",
            "verification_execution_status": "RUNNING",
            "generalized_analysis_status": "RUNNING",
            "agent_run_status": "RUNNING",
            "agent_run_error": None,
            "generalized_analysis_error": None,
        },
    )
    db.commit()
    db.refresh(session)

    try:
        policy = load_agent_runtime_policy()
        state = build_generalized_verification_graph(policy=policy).invoke(
            {
                "session_id": session.id,
                "filename": session.filename,
                "file_path": session.file_path,
                "runtime_policy": policy,
            }
        )
        workspace = WorkspacePayload.model_validate(state["workspace_payload"])
        final_verdict = FinalVerdict.model_validate(state["final_verdict"])
        review_state = SessionState.PENDING_HUMAN_REVIEW

        completion_values = {}
        try:
            completion_values = _build_completion_values(
                db,
                session.id,
                reviewer_ref,
                {
                    "outcome": final_verdict.outcome,
                    "reason_codes": final_verdict.reason_codes,
                    "connector_ids": final_verdict.connector_ids,
                    "finding_counts": _finding_counts_from_workspace_summary(workspace.summary),
                },
            )
        except Exception as exc:  # pragma: no cover - audit backend may be unavailable in tests
            LOGGER.warning("GENERALIZED_AUDIT_FALLBACK session_id=%s error=%s", session.id, exc)
            workspace.audit.append(
                WorkspaceAuditEntry(
                    stage="audit",
                    message="Audit bundle persistence failed; workspace payload remains available.",
                    level="WARNING",
                    timestamp=_utc_now(),
                )
            )

        workspace = workspace.model_copy(
            update={
                "status": review_state,
                "ui_status": "Ready for human review",
                "final_verdict": final_verdict,
                "summary": workspace.summary.model_copy(
                    update={
                        "matching_score": final_verdict.matching_score,
                        "visual_match_probability": final_verdict.visual_match_probability,
                        "risk_level": final_verdict.risk_level,
                    }
                ),
            }
        )
        workspace = sanitize_workspace_payload(workspace)

        repository.complete_processing(
            db,
            session.id,
            review_state,
            final_verdict.outcome,
            final_verdict.reason_codes,
            final_verdict.connector_ids,
            extra_values={
                "workspace_payload": workspace.model_dump(mode="json"),
                "verification_execution_summary_payload": None,
                "verification_execution_status": "READY",
                "generalized_analysis_status": "READY",
                "agent_run_status": "READY" if not state.get("gemini_fallback_used") else "FALLBACK",
                "agent_run_summary_payload": None,
                "provider_execution_traces_payload": None,
                "provider_execution_status": "READY",
                "provider_operating_mode": "DEMO_MOCK",
                **completion_values,
            },
        )
        db.commit()
        return workspace
    except Exception as exc:
        LOGGER.exception("GENERALIZED_VERIFICATION_FAILED session_id=%s", session.id)
        repository.fail_processing(
            db,
            session.id,
            SessionState.FAILED_RETRIABLE,
            ["GENERALIZED_PIPELINE_FAILED"],
            extra_values={
                "verification_execution_status": "FAILED",
                "generalized_analysis_status": "FAILED",
                "generalized_analysis_error": str(exc),
                "agent_run_status": "FAILED",
                "agent_run_error": str(exc),
            },
        )
        db.commit()
        raise


def get_workspace_payload_for_session(session: SessionModel) -> WorkspacePayload:
    persisted = session.workspace_payload or session.verification_execution_summary_payload
    if isinstance(persisted, dict):
        try:
            workspace = sanitize_workspace_payload(WorkspacePayload.model_validate(persisted))
            return _overlay_live_workspace_state(workspace, session)
        except Exception:
            LOGGER.warning("WORKSPACE_PAYLOAD_INVALID session_id=%s", session.id)

    return _overlay_live_workspace_state(sanitize_workspace_payload(_build_placeholder_workspace(session)), session)


def get_live_workspace_payload_for_session(db, session: SessionModel) -> WorkspacePayload:
    workspace = get_workspace_payload_for_session(session)
    audit_receipt = get_latest_audit_receipt(db, session.id)
    if audit_receipt is None:
        return workspace
    return workspace.model_copy(update={"audit_receipt": serialize_audit_summary(audit_receipt)})


def _overlay_live_workspace_state(workspace: WorkspacePayload, session: SessionModel) -> WorkspacePayload:
    actions = _merge_live_close_action(workspace.actions, session.status)
    action_flags = {"can_close": _close_enabled_for_status(session.status)}
    privacy = {**(workspace.privacy or {}), **WORKSPACE_PRIVACY_METADATA}

    return sanitize_workspace_payload(
        workspace.model_copy(
            update={
                "status": session.status,
                "ui_status": _ui_status_for_session(session.status),
                "actions": actions,
                "action_flags": action_flags,
                "privacy": privacy,
            }
        )
    )


def _merge_live_close_action(actions: list[WorkspaceAction], session_status: str) -> list[WorkspaceAction]:
    close_enabled = _close_enabled_for_status(session_status)
    merged: list[WorkspaceAction] = []
    found_can_close = False
    for action in actions:
        action_id = _action_id(action)
        if action_id == "can_close":
            found_can_close = True
            merged.append(action.model_copy(update={"enabled": close_enabled}))
        else:
            merged.append(action)
    if not found_can_close:
        close_action = next((action for action in _default_actions(session_status) if action.action_id == "can_close"), None)
        if close_action is not None:
            merged.append(close_action.model_copy(update={"enabled": close_enabled}))
    return merged


def _action_id(action: WorkspaceAction | dict[str, Any]) -> str:
    if isinstance(action, WorkspaceAction):
        return str(action.action_id or "")
    return str(action.get("action_id") or action.get("id") or action.get("actionId") or "")


def _close_enabled_for_status(session_status: str) -> bool:
    return session_status in HUMAN_FINAL_WORKSPACE_STATES


def _ui_status_for_session(session_status: str) -> str:
    if session_status == SessionState.PENDING_HUMAN_REVIEW:
        return "Ready for human review"
    if session_status == SessionState.HUMAN_APPROVED:
        return "Human approved"
    if session_status == SessionState.HUMAN_REJECTED:
        return "Human rejected"
    if session_status == SessionState.MANUAL_REVIEW_REQUIRED:
        return "Manual review required"
    if session_status in {SessionState.VERIFIED_GREEN, SessionState.VERIFIED_AMBER, SessionState.VERIFIED_RED}:
        return "Ready"
    if session_status == SessionState.VERIFYING:
        return "Verifying"
    return session_status


def _build_placeholder_workspace(session: SessionModel) -> WorkspacePayload:
    outcome = session.trust_outcome or "AMBER"
    final_verdict = FinalVerdict(
        outcome=outcome if outcome in {"GREEN", "AMBER", "RED"} else "AMBER",
        reason_codes=list(session.reason_codes or []),
        connector_ids=list(session.connector_ids or []),
        explanation="Verification has not produced a persisted workspace payload yet.",
        risk_level="LOW" if outcome == "GREEN" else "HIGH" if outcome == "RED" else "MEDIUM",
        matching_score=0.0,
        visual_match_probability=0.0,
    )
    return WorkspacePayload(
        session_id=session.id,
        status=session.status,
        ui_status="READY" if session.status in {SessionState.VERIFIED_GREEN, SessionState.VERIFIED_AMBER, SessionState.VERIFIED_RED} else "PENDING",
        document=WorkspaceDocument(filename=session.filename),
        summary=WorkspaceSummary(risk_level=final_verdict.risk_level, active_exceptions=list(session.reason_codes or [])),
        fields=[],
        verifiers=[],
        final_verdict=final_verdict,
        audit=[
            WorkspaceAuditEntry(
                stage="workspace",
                message="Workspace payload is not available yet.",
                timestamp=_utc_now(),
            )
        ],
        actions=_default_actions(session.status),
    )


def _default_actions(session_status: str = "") -> list[WorkspaceAction]:
    pending_human_review = session_status in {
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
        SessionState.PENDING_HUMAN_REVIEW,
    }
    human_final = session_status in {
        SessionState.HUMAN_APPROVED,
        SessionState.HUMAN_REJECTED,
        SessionState.MANUAL_REVIEW_REQUIRED,
    }
    return [
        WorkspaceAction(action_id="can_rerun", label="Rerun"),
        WorkspaceAction(action_id="can_manual_override", label="Manual Override"),
        WorkspaceAction(action_id="can_export_report", label="Export Report", enabled=not pending_human_review),
        WorkspaceAction(action_id="can_close", label="Close Session", enabled=not pending_human_review or human_final),
        WorkspaceAction(action_id="can_approve", label="Approve", enabled=pending_human_review),
        WorkspaceAction(action_id="can_reject", label="Reject", enabled=pending_human_review),
        WorkspaceAction(action_id="can_manual_review", label="Manual Review", enabled=pending_human_review),
    ]


def _finding_counts_from_workspace_summary(summary: WorkspaceSummary) -> dict[str, int]:
    return {
        "green": max(0, int(summary.green_count or 0)),
        "amber": max(0, int(summary.amber_count or 0)),
        "red": max(0, int(summary.red_count or 0)),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
