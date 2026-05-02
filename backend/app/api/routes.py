from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from ..audit.service import upsert_final_review_receipt
from ..auth.routes import get_current_user
from ..db.database import get_db
from ..sessions.constants import SessionState
from ..sessions.models import Session as SessionModel
from ..workflow import repository
from ..agent_orchestration.contracts import (
    AgentDocumentUnderstanding,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
    SessionAgentRunStatus,
)
from ..verifier_providers import (
    ProviderCapabilityCollection,
    ProviderExecutionTraceCollection,
    SessionProviderOperatingMode,
    SessionProviderExecutionStatus,
    get_provider_capabilities_for_session,
)
from ..demo_profiles import DemoProfileSummary
from ..verifier_execution.contracts import (
    CredentialVerificationBundleCollection,
    SessionVerificationExecutionStatus,
    VerificationTaskResultCollection,
)
from ..verification_domain.contracts import (
    CredentialAuditCollection,
    DocumentProfile,
    DocumentVerificationSummary,
    SessionAnalysisStatus,
    SessionCredentialCollection,
    SessionVerificationPlan,
)
from ..agent_orchestration.graph import build_generalized_verification_graph
from ..agent_orchestration.sanitization import sanitize_workspace_payload
from ..agent_orchestration.schemas import WorkspacePayload
from ..workflow.runtime import extract_document_payload
from ..workflow.runtime import get_result_response, get_status_response, serialize_session
from ..workflow.service import start_verification


router = APIRouter(tags=["workflow"])
LOGGER = logging.getLogger(__name__)


ReviewDecisionValue = Literal["APPROVE", "REJECT", "NEEDS_MANUAL_REVIEW"]


class ReviewDecisionRequest(BaseModel):
    decision: ReviewDecisionValue
    reviewer_note: str | None = None

    @model_validator(mode="after")
    def require_note_for_manual_review(self) -> "ReviewDecisionRequest":
        if self.decision == "NEEDS_MANUAL_REVIEW" and not (self.reviewer_note or "").strip():
            raise ValueError("reviewer_note is required when decision is NEEDS_MANUAL_REVIEW")
        return self


class ReviewDecisionResponse(BaseModel):
    session_id: str
    status: str
    final_decision: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW_REQUIRED"]
    cleanup_ready: bool
    audit_receipt_id: str | None = None


def _sensitive_artifact_gone() -> None:
    raise HTTPException(
        status_code=410,
        detail="Detailed verification artifacts are processing-only and are not persisted.",
    )


def _get_owned_session(db: Session, session_id: str, user: str) -> SessionModel:
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user:
        raise HTTPException(status_code=403, detail="Not authorized")
    return session


def _get_session_extraction_payload(session: SessionModel) -> dict[str, Any]:
    if (
        isinstance(session.extraction_payload, dict)
        and isinstance(session.extraction_payload.get("view"), dict)
        and isinstance(session.extraction_payload.get("connector_input"), dict)
    ):
        return session.extraction_payload

    if not session.file_path:
        raise HTTPException(status_code=409, detail="Upload a PDF before opening the workspace")

    file_path = Path(session.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found on disk")

    try:
        return extract_document_payload(file_path)
    except Exception as exc:
        LOGGER.exception("WORKSPACE_EXTRACTION_FAILED session_id=%s", session.id)
        raise HTTPException(status_code=500, detail="Extraction payload could not be loaded") from exc


def _build_workspace_payload(session: SessionModel) -> WorkspacePayload:
    extraction_payload = _get_session_extraction_payload(session)
    graph = build_generalized_verification_graph()
    initial_state = {
        "session_id": session.id,
        "filename": session.filename,
        "file_path": session.file_path,
        "session_status": session.status,
        "extraction_payload": extraction_payload,
    }

    try:
        final_state = graph.invoke(initial_state)
    except Exception as exc:
        LOGGER.exception("WORKSPACE_GRAPH_FAILED session_id=%s", session.id)
        raise HTTPException(status_code=500, detail="Workspace graph execution failed") from exc

    workspace_payload = final_state.get("workspace_payload") if isinstance(final_state, dict) else None
    if not isinstance(workspace_payload, dict):
        raise HTTPException(status_code=500, detail="Workspace graph did not produce a workspace payload")

    return sanitize_workspace_payload(WorkspacePayload.model_validate(workspace_payload))


def _review_status_for_decision(decision: ReviewDecisionValue) -> tuple[str, str]:
    if decision == "APPROVE":
        return SessionState.HUMAN_APPROVED, "APPROVED"
    if decision == "REJECT":
        return SessionState.HUMAN_REJECTED, "REJECTED"
    return SessionState.MANUAL_REVIEW_REQUIRED, "MANUAL_REVIEW_REQUIRED"


def _completed_review_workspace(workspace: WorkspacePayload | dict) -> WorkspacePayload:
    if isinstance(workspace, dict):
        workspace = WorkspacePayload.model_validate(workspace)
    return workspace.model_copy(
        update={
            "status": SessionState.PENDING_HUMAN_REVIEW,
            "ui_status": "Ready for human review",
        }
    )


def _persist_workspace_contract(db: Session, session: SessionModel, workspace: WorkspacePayload) -> None:
    workspace = sanitize_workspace_payload(_completed_review_workspace(workspace))
    session.status = SessionState.PENDING_HUMAN_REVIEW
    session.worker_phase = "COMPLETED"
    session.trust_outcome = workspace.final_verdict.outcome
    session.reason_codes = list(workspace.final_verdict.reason_codes or [])
    session.connector_ids = list(workspace.final_verdict.connector_ids or [])
    session.workspace_payload = workspace.model_dump(mode="json")
    session.verification_execution_status = "READY"
    session.generalized_analysis_status = "READY"
    session.provider_execution_status = "READY"
    session.provider_operating_mode = "DEMO_MOCK"
    db.commit()
    db.refresh(session)


@router.post("/session/{session_id}/verify")
def verify_session_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict:
    session = _get_owned_session(db, session_id, user)
    if not session.file_path:
        raise HTTPException(status_code=409, detail="Upload a PDF before verification")
    if session.status in {SessionState.PENDING_CLEANUP, SessionState.PURGE_COMPLETE, SessionState.FAILED_PURGED}:
        raise HTTPException(status_code=409, detail="Session is already closed")

    if session.status not in {
        SessionState.UPLOADED_PENDING_REVIEW,
        SessionState.FAILED_RETRIABLE,
    }:
        raise HTTPException(status_code=409, detail="Session is not ready for verification")

    start_result = start_verification(
        db,
        session.id,
        worker_id=user,
    )
    if start_result == "NO_OP":
        raise HTTPException(status_code=409, detail="Verification is already in progress")
    if start_result == "FAILED":
        raise HTTPException(status_code=500, detail="Verification could not be started")

    db.refresh(session)
    return serialize_session(db, session)


@router.get("/session/{session_id}/status")
def get_session_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict:
    session = _get_owned_session(db, session_id, user)
    payload = get_status_response(session)
    LOGGER.info("STATUS_FETCHED session_id=%s state=%s", session.id, session.status)
    return payload


@router.get("/session/{session_id}/result")
def get_session_result_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict:
    session = _get_owned_session(db, session_id, user)
    payload = get_result_response(session)
    LOGGER.info("RESULT_FETCHED session_id=%s state=%s", session.id, session.status)
    return payload


@router.get("/session/{session_id}/agent-document-understanding", response_model=AgentDocumentUnderstanding)
def get_session_agent_document_understanding_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> AgentDocumentUnderstanding:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/agent-credential-candidates", response_model=SessionAgentCredentialCandidateCollection)
def get_session_agent_credential_candidates_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionAgentCredentialCandidateCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/agent-route-recommendations", response_model=SessionAgentRouteRecommendationCollection)
def get_session_agent_route_recommendations_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionAgentRouteRecommendationCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/agent-run-status", response_model=SessionAgentRunStatus)
def get_session_agent_run_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionAgentRunStatus:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/provider-execution-traces", response_model=ProviderExecutionTraceCollection)
def get_session_provider_execution_traces_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> ProviderExecutionTraceCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/provider-execution-status", response_model=SessionProviderExecutionStatus)
def get_session_provider_execution_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionProviderExecutionStatus:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/provider-operating-mode", response_model=SessionProviderOperatingMode)
def get_session_provider_operating_mode_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionProviderOperatingMode:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/demo-profile", response_model=DemoProfileSummary)
def get_session_demo_profile_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> DemoProfileSummary:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/provider-capabilities", response_model=ProviderCapabilityCollection)
def get_session_provider_capabilities_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> ProviderCapabilityCollection:
    session = _get_owned_session(db, session_id, user)
    payload = get_provider_capabilities_for_session(session)
    LOGGER.info("PROVIDER_CAPABILITIES_FETCHED session_id=%s count=%s", session.id, len(payload.capabilities))
    return payload


@router.get("/session/{session_id}/verification-task-results", response_model=VerificationTaskResultCollection)
def get_session_verification_task_results_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> VerificationTaskResultCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/credential-bundles", response_model=CredentialVerificationBundleCollection)
def get_session_credential_bundles_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> CredentialVerificationBundleCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/verification-execution-status", response_model=SessionVerificationExecutionStatus)
def get_session_verification_execution_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionVerificationExecutionStatus:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/credentials", response_model=SessionCredentialCollection)
def get_session_credentials_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionCredentialCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/verification-plan", response_model=SessionVerificationPlan)
def get_session_verification_plan_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionVerificationPlan:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/credential-audits", response_model=CredentialAuditCollection)
def get_session_credential_audits_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> CredentialAuditCollection:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/verification-summary", response_model=DocumentVerificationSummary)
def get_session_verification_summary_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> DocumentVerificationSummary:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/document-profile", response_model=DocumentProfile)
def get_session_document_profile_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> DocumentProfile:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.get("/session/{session_id}/analysis-status", response_model=SessionAnalysisStatus)
def get_session_analysis_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionAnalysisStatus:
    del session_id, db, user
    _sensitive_artifact_gone()


@router.post("/api/v1/verification-sessions/{session_id}/run", response_model=WorkspacePayload)
def run_generalized_verification_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> WorkspacePayload:
    session = _get_owned_session(db, session_id, user)
    if not session.file_path:
        raise HTTPException(status_code=409, detail="Upload a PDF before verification")
    if not Path(session.file_path).exists():
        raise HTTPException(status_code=404, detail="Document not found on disk")
    if session.status in {SessionState.PENDING_CLEANUP, SessionState.PURGE_COMPLETE, SessionState.FAILED_PURGED}:
        raise HTTPException(status_code=409, detail="Session is already closed")
    if session.status == SessionState.VERIFYING:
        # Already running, just return the current (placeholder) workspace
        return _build_workspace_payload(session)

    if session.status in {
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
        SessionState.PENDING_HUMAN_REVIEW,
        SessionState.HUMAN_APPROVED,
        SessionState.HUMAN_REJECTED,
        SessionState.MANUAL_REVIEW_REQUIRED,
    }:
        # Already finished, return the persisted workspace
        return _build_workspace_payload(session)

    if session.status not in {
        SessionState.UPLOADED_PENDING_REVIEW,
        SessionState.FAILED_RETRIABLE,
    }:
        raise HTTPException(status_code=409, detail=f"Session is not ready for verification (current state: {session.status})")

    start_result = start_verification(
        db,
        session.id,
        worker_id=user,
    )
    if start_result == "NO_OP":
        raise HTTPException(status_code=409, detail="Verification is already in progress")
    if start_result == "FAILED":
        raise HTTPException(status_code=500, detail="Verification could not be started")

    try:
        workspace = _completed_review_workspace(_build_workspace_payload(session))
        _persist_workspace_contract(db, session, workspace)
        return workspace
    except Exception as exc:
        LOGGER.exception("GENERALIZED_VERIFICATION_FAILED session_id=%s", session.id)
        raise HTTPException(status_code=500, detail="Generalized verification failed") from exc


@router.post("/api/v1/verification-sessions/{session_id}/review-decision", response_model=ReviewDecisionResponse)
def review_decision_route(
    session_id: str,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> ReviewDecisionResponse:
    session = _get_owned_session(db, session_id, user)
    allowed_states = {
        SessionState.PENDING_HUMAN_REVIEW,
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
    }
    if session.status not in allowed_states:
        raise HTTPException(status_code=409, detail="Session is not ready for human review")

    final_state, final_decision = _review_status_for_decision(request.decision)
    try:
        if session.status in {
            SessionState.VERIFIED_GREEN,
            SessionState.VERIFIED_AMBER,
            SessionState.VERIFIED_RED,
        }:
            repository.transition_state(db, session.id, SessionState.PENDING_HUMAN_REVIEW)

        repository.transition_state(db, session.id, final_state)
        audit_receipt = upsert_final_review_receipt(
            db,
            session,
            reviewer_ref=user,
            reviewer_decision=final_decision,
            reviewer_note=request.reviewer_note,
        )
        db.commit()
        db.refresh(session)
    except Exception as exc:
        db.rollback()
        LOGGER.exception("REVIEW_DECISION_FAILED session_id=%s decision=%s", session.id, request.decision)
        raise HTTPException(status_code=409, detail="Review decision could not be applied") from exc

    return ReviewDecisionResponse(
        session_id=session.id,
        status=session.status,
        final_decision=final_decision,
        cleanup_ready=True,
        audit_receipt_id=audit_receipt.audit_event_id,
    )


@router.get("/api/v1/verification-sessions/{session_id}/workspace", response_model=dict)
def get_generalized_workspace_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> WorkspacePayload:
    session = _get_owned_session(db, session_id, user)
    if session.status in {SessionState.PENDING_CLEANUP, SessionState.PURGE_COMPLETE, SessionState.FAILED_PURGED}:
        raise HTTPException(status_code=409, detail="Session is already closed")
    if not session.workspace_payload:
        raise HTTPException(
            status_code=409,
            detail="Workspace not ready. Run verification first."
        )

    return sanitize_workspace_payload(WorkspacePayload.model_validate(session.workspace_payload)).model_dump(mode="json")

def build_workspace_response(session):
    # Compatibility-only response helper for older callers. The canonical
    # frontend contract is WorkspacePayload from the /workspace endpoint.
    workspace = sanitize_workspace_payload(session.workspace_payload or {})

    document = workspace.get("document", {})
    summary = workspace.get("summary", {})
    fields = workspace.get("fields", [])
    verifiers = workspace.get("verifiers", [])
    audit = workspace.get("audit", [])
    actions = workspace.get("actions", [])

    # 🔹 FINDINGS (fields → findings)
    findings = [
        {
            "field_id": f.get("field_id"),
            "label": f.get("label"),
            "value": f.get("extracted_value"),
            "status": f.get("status"),
            "confidence": f.get("final_confidence"),
            "reason_codes": f.get("reason_codes", []),
            "source": f.get("source_api"),
            "message": f.get("audit_message"),
        }
        for f in fields
    ]

    # 🔹 VERIFICATION TASKS (verifiers → tasks)
    verification_tasks = [
        {
            "task_id": v.get("connector_id"),
            "status": v.get("status"),
            "confidence": v.get("confidence"),
            "reason_codes": v.get("reason_codes", []),
            "source": v.get("source_api"),
            "field_ids": v.get("field_ids", []),
        }
        for v in verifiers
    ]

    # 🔹 TASK RESULTS (can be same as tasks or expanded later)
    task_results = verification_tasks

    # 🔹 AUDIT SUMMARY (simplified)
    audit_summary = [
        {
            "stage": a.get("stage"),
            "message": a.get("message"),
            "level": a.get("level"),
        }
        for a in audit
    ]

    return {
        "session_id": workspace.get("session_id") or str(session.id),
        "status": workspace.get("status"),
        "ui_status": workspace.get("ui_status"),

        "document": document,
        "summary": summary,

        "findings": findings,
        "verification_tasks": verification_tasks,
        "task_results": task_results,

        "audit_summary": audit_summary,
        "actions": actions,
    }
