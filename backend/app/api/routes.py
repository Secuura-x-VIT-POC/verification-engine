from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.routes import get_current_user
from ..db.database import get_db
from ..sessions.constants import SessionState
from ..sessions.models import Session as SessionModel
from ..verifier_execution import (
    CredentialVerificationBundleCollection,
    SessionVerificationExecutionStatus,
    VerificationTaskResultCollection,
    get_credential_bundles_for_session,
    get_verification_execution_status_for_session,
    get_verification_task_results_for_session,
)
from ..verification_domain import (
    CredentialAuditCollection,
    DocumentProfile,
    DocumentVerificationSummary,
    SessionAnalysisStatus,
    SessionCredentialCollection,
    SessionVerificationPlan,
    get_analysis_status_for_session,
    get_credential_audits_for_session,
    get_credentials_for_session,
    get_document_profile_for_session,
    get_verification_plan_for_session,
    get_verification_summary_for_session,
)
from ..workflow.runtime import get_result_response, get_status_response, run_verification, serialize_session


router = APIRouter(tags=["workflow"])
LOGGER = logging.getLogger(__name__)


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
        SessionState.VERIFYING,
        SessionState.FAILED_RETRIABLE,
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
    }:
        raise HTTPException(status_code=409, detail="Session is not ready for verification")

    if session.status not in {
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
    }:
        session = run_verification(db, session, user)

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


@router.get("/session/{session_id}/verification-task-results", response_model=VerificationTaskResultCollection)
def get_session_verification_task_results_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> VerificationTaskResultCollection:
    session = _get_owned_session(db, session_id, user)
    payload = get_verification_task_results_for_session(session)
    LOGGER.info("GENERALIZED_TASK_RESULTS_FETCHED session_id=%s results=%s", session.id, len(payload.results))
    return payload


@router.get("/session/{session_id}/credential-bundles", response_model=CredentialVerificationBundleCollection)
def get_session_credential_bundles_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> CredentialVerificationBundleCollection:
    session = _get_owned_session(db, session_id, user)
    payload = get_credential_bundles_for_session(session)
    LOGGER.info("GENERALIZED_BUNDLES_FETCHED session_id=%s bundles=%s", session.id, len(payload.bundles))
    return payload


@router.get("/session/{session_id}/verification-execution-status", response_model=SessionVerificationExecutionStatus)
def get_session_verification_execution_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionVerificationExecutionStatus:
    session = _get_owned_session(db, session_id, user)
    payload = get_verification_execution_status_for_session(session)
    LOGGER.info(
        "GENERALIZED_EXECUTION_STATUS_FETCHED session_id=%s execution_status=%s",
        session.id,
        payload.verification_execution_status,
    )
    return payload


@router.get("/session/{session_id}/credentials", response_model=SessionCredentialCollection)
def get_session_credentials_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionCredentialCollection:
    session = _get_owned_session(db, session_id, user)
    payload = get_credentials_for_session(session)
    LOGGER.info("GENERALIZED_CREDENTIALS_FETCHED session_id=%s count=%s", session.id, len(payload.credentials))
    return payload


@router.get("/session/{session_id}/verification-plan", response_model=SessionVerificationPlan)
def get_session_verification_plan_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionVerificationPlan:
    session = _get_owned_session(db, session_id, user)
    payload = get_verification_plan_for_session(session)
    LOGGER.info("GENERALIZED_PLAN_FETCHED session_id=%s tasks=%s", session.id, len(payload.tasks))
    return payload


@router.get("/session/{session_id}/credential-audits", response_model=CredentialAuditCollection)
def get_session_credential_audits_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> CredentialAuditCollection:
    session = _get_owned_session(db, session_id, user)
    payload = get_credential_audits_for_session(session)
    LOGGER.info("GENERALIZED_AUDITS_FETCHED session_id=%s audits=%s", session.id, len(payload.audits))
    return payload


@router.get("/session/{session_id}/verification-summary", response_model=DocumentVerificationSummary)
def get_session_verification_summary_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> DocumentVerificationSummary:
    session = _get_owned_session(db, session_id, user)
    payload = get_verification_summary_for_session(session)
    LOGGER.info("GENERALIZED_SUMMARY_FETCHED session_id=%s outcome=%s", session.id, payload.overall_outcome)
    return payload


@router.get("/session/{session_id}/document-profile", response_model=DocumentProfile)
def get_session_document_profile_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> DocumentProfile:
    session = _get_owned_session(db, session_id, user)
    payload = get_document_profile_for_session(session)
    LOGGER.info("GENERALIZED_PROFILE_FETCHED session_id=%s family=%s", session.id, payload.document_family)
    return payload


@router.get("/session/{session_id}/analysis-status", response_model=SessionAnalysisStatus)
def get_session_analysis_status_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> SessionAnalysisStatus:
    session = _get_owned_session(db, session_id, user)
    payload = get_analysis_status_for_session(session)
    LOGGER.info(
        "GENERALIZED_STATUS_FETCHED session_id=%s analysis_status=%s",
        session.id,
        payload.generalized_analysis_status,
    )
    return payload
