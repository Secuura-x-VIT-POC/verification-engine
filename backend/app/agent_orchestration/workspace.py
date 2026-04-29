from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

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
        verified_state = _state_for_outcome(final_verdict.outcome)

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
                "status": verified_state,
                "ui_status": "READY",
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
            verified_state,
            final_verdict.outcome,
            final_verdict.reason_codes,
            final_verdict.connector_ids,
            extra_values={
                "verification_execution_summary_payload": workspace.model_dump(mode="json"),
                "verification_execution_status": "READY",
                "generalized_analysis_status": "READY",
                "agent_run_status": "READY" if not state.get("gemini_fallback_used") else "FALLBACK",
                "agent_run_summary_payload": {
                    "provider": policy.provider_key,
                    "model": policy.gemini_model,
                    "fallback_used": bool(state.get("gemini_fallback_used")),
                    "gemini_errors": list(state.get("gemini_errors") or []),
                },
                "provider_execution_traces_payload": [verifier.model_dump(mode="json") for verifier in workspace.verifiers],
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
    persisted = session.verification_execution_summary_payload
    if isinstance(persisted, dict):
        try:
            return sanitize_workspace_payload(WorkspacePayload.model_validate(persisted))
        except Exception:
            LOGGER.warning("WORKSPACE_PAYLOAD_INVALID session_id=%s", session.id)

    return sanitize_workspace_payload(_build_placeholder_workspace(session))


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


def _state_for_outcome(outcome: str) -> str:
    if outcome == "GREEN":
        return SessionState.VERIFIED_GREEN
    if outcome == "RED":
        return SessionState.VERIFIED_RED
    return SessionState.VERIFIED_AMBER


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
