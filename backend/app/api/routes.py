from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.routes import get_current_user
from ..db.database import get_db
from ..sessions.constants import SessionState
from ..sessions.models import Session as SessionModel
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
