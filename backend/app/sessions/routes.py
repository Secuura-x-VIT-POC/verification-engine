from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth.routes import get_current_user
from ..db.database import get_db
from ..security.pdf_validator import PDFValidationError, validate_pdf
from ..workflow import repository as workflow_repository
from ..workflow.runtime import close_session, serialize_session
from .constants import SessionState
from .models import Session as SessionModel
from .models import UploadToken


router = APIRouter(tags=["sessions"])


def _uploads_dir() -> Path:
    upload_dir = Path("uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _get_session_or_404(db: Session, session_id: str) -> SessionModel:
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _get_owned_session(db: Session, session_id: str, user: str) -> SessionModel:
    session = _get_session_or_404(db, session_id)
    if session.user_id != user:
        raise HTTPException(status_code=403, detail="Not authorized")
    return session


@router.post("/sessions")
def create_session(
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict[str, str]:
    new_session = SessionModel(user_id=user)
    db.add(new_session)
    db.commit()
    return {"session_id": new_session.id, "status": new_session.status}


@router.get("/sessions/{session_id}")
def get_session_details(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict:
    session = _get_owned_session(db, session_id, user)
    return serialize_session(db, session)


@router.post("/sessions/{session_id}/upload-token")
def generate_upload_token(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict[str, str]:
    session = _get_owned_session(db, session_id, user)
    if session.status not in {SessionState.CREATED, SessionState.UPLOAD_PENDING}:
        raise HTTPException(status_code=409, detail="Upload token can only be issued for new sessions")

    upload_token = UploadToken(
        token=str(uuid.uuid4()),
        session_id=session_id,
        is_used=False,
    )
    if session.status == SessionState.CREATED:
        workflow_repository.transition_state(
            db,
            session_id,
            SessionState.UPLOAD_PENDING,
        )
    db.add(upload_token)
    db.commit()
    db.refresh(session)

    return {
        "upload_token": upload_token.token,
        "expires_at": upload_token.expires_at.isoformat(),
    }


@router.post("/upload")
def upload_file(
    token: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict[str, str]:
    upload_token = db.query(UploadToken).filter(UploadToken.token == token).first()
    if upload_token is None:
        raise HTTPException(status_code=404, detail="Invalid token")
    if upload_token.is_used:
        raise HTTPException(status_code=409, detail="Token already used")
    if upload_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")

    session = _get_owned_session(db, upload_token.session_id, user)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content = file.file.read()
    try:
        validate_pdf(content)
    except PDFValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    safe_filename = f"{uuid.uuid4()}.pdf"
    file_path = _uploads_dir() / safe_filename
    file_path.write_bytes(content)

    upload_token.is_used = True
    upload_token.used_at = datetime.utcnow()
    workflow_repository.transition_state(
        db,
        session.id,
        SessionState.UPLOADED_PENDING_REVIEW,
        extra_values={
            "filename": file.filename,
            "file_path": str(file_path),
            "uploaded_at": datetime.utcnow(),
            "worker_phase": None,
            "reason_codes": [],
            "connector_ids": [],
            "trust_outcome": None,
            "extraction_payload": None,
            "connector_payload": None,
            "document_profile_payload": None,
            "generalized_credentials_payload": None,
            "verification_plan_payload": None,
            "verification_task_results_payload": None,
            "credential_verification_bundles_payload": None,
            "verification_execution_summary_payload": None,
            "credential_audits_payload": None,
            "verification_summary_payload": None,
            "generalized_analysis_status": "NOT_STARTED",
            "generalized_analysis_error": None,
            "verification_execution_status": "NOT_STARTED",
            "verification_execution_error": None,
            "document_commitment": None,
            "audit_receipt_id": None,
            "purge_status": None,
            "purge_error": None,
        },
    )
    db.commit()
    db.refresh(session)

    return {
        "message": "File uploaded securely",
        "filename": safe_filename,
        "session_id": session.id,
        "status": session.status,
    }


@router.get("/sessions/{session_id}/document")
def get_session_document(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    session = _get_owned_session(db, session_id, user)
    if not session.file_path:
        raise HTTPException(status_code=404, detail="Document has already been purged")

    file_path = Path(session.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found on disk")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=session.filename or file_path.name,
    )


@router.post("/sessions/{session_id}/close")
def close_session_route(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict:
    session = _get_owned_session(db, session_id, user)
    closed_session = close_session(db, session)
    return serialize_session(db, closed_session)
