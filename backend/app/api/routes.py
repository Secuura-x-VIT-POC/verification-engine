from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.routes import get_current_user
from ..db.database import get_db
from ..sessions.constants import SessionState
from ..sessions.models import Session as SessionModel
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
from ..agent_orchestration.schemas import WorkspacePayload
from ..agent_orchestration.workspace import (
    get_workspace_payload_for_session,
    run_generalized_verification_session,
)
from ..workflow.runtime import get_result_response, get_status_response, serialize_session
from ..workflow.service import start_verification


router = APIRouter(tags=["workflow"])
LOGGER = logging.getLogger(__name__)


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
    if session.status in {SessionState.PENDING_CLEANUP, SessionState.PURGE_COMPLETE, SessionState.FAILED_PURGED}:
        raise HTTPException(status_code=409, detail="Session is already closed")
    if session.status not in {
        SessionState.UPLOADED_PENDING_REVIEW,
        SessionState.FAILED_RETRIABLE,
    }:
        raise HTTPException(status_code=409, detail="Session is not ready for generalized verification")

    return run_generalized_verification_session(db, session, reviewer_ref=user)


@router.get("/api/v1/verification-sessions/{session_id}/workspace", response_model=WorkspacePayload)
def get_generalized_workspace_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> WorkspacePayload:
    session = _get_owned_session(db, session_id, user)
    return get_workspace_payload_for_session(session)
