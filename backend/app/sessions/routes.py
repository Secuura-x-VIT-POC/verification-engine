from __future__ import annotations

import uuid
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.routes import get_current_user
from ..db.database import get_db
from ..security.pdf_validator import (
    PDF_ACTIVE_CONTENT_STRIPPED_NOTICE,
    PDFValidationError,
    make_image_only_pdf,
    report_to_safe_dict,
    safe_pdf_flattening_enabled,
    validate_pdf_report,
    validate_pdf_upload_metadata,
    write_pdf_security_sidecar,
)
from ..workflow import repository as workflow_repository
from ..workflow.runtime import close_session, serialize_session
from .constants import SessionState
from .models import Session as SessionModel
from .models import UploadToken


router = APIRouter(tags=["sessions"])
LOGGER = logging.getLogger(__name__)


class UploadResponse(BaseModel):
    message: str
    filename: str
    session_id: str
    status: str
    notices: list[str] = Field(default_factory=list)


def normalize_notices(raw_notices: Any) -> list[str]:
    """
    Normalizes notice codes into a safe list of strings.
    Strips empty values, never includes raw exception text/paths/PII.
    """
    if not raw_notices:
        return []
        
    extracted = []
    if isinstance(raw_notices, str):
        extracted.append(raw_notices)
    elif isinstance(raw_notices, (list, tuple, set)):
        for item in raw_notices:
            if isinstance(item, str):
                extracted.append(item)
            elif hasattr(item, "get") and hasattr(item, "keys"):
                for key in ["code", "warning_code", "reason_code", "type", "stage", "message"]:
                    val = item.get(key)
                    if val:
                        extracted.append(str(val))
            else:
                extracted.append(str(item))
    elif hasattr(raw_notices, "get") and hasattr(raw_notices, "keys"):
        for key in ["code", "warning_code", "reason_code", "type", "stage", "message"]:
            val = raw_notices.get(key)
            if val:
                extracted.append(str(val))
        
    safe_notices = []
    for code in extracted:
        code = code.strip()
        if not code:
            continue
        if code.isupper() and all(c.isalnum() or c == '_' for c in code):
            if code not in safe_notices:
                safe_notices.append(code)
                
    return sorted(safe_notices)


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
    return {"session_id": str(new_session.id), "status": str(new_session.status)}


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
        "upload_token": str(upload_token.token),
        "expires_at": upload_token.expires_at.isoformat(),
    }


@router.post("/upload")
def upload_file(
    token: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> UploadResponse:
    upload_token = db.query(UploadToken).filter(UploadToken.token == token).first()
    if upload_token is None:
        raise HTTPException(status_code=404, detail="Invalid token")
    if upload_token.is_used:
        raise HTTPException(status_code=409, detail="Token already used")
    if upload_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")

    session = _get_owned_session(db, str(upload_token.session_id), user)
    try:
        validate_pdf_upload_metadata(file.filename, file.content_type)
    except PDFValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = file.file.read()
    upload_notices: list[str] = []
    security_payload: dict = {}
    try:
        scan_started = time.perf_counter()
        report = validate_pdf_report(content, allow_active_content=safe_pdf_flattening_enabled())
        LOGGER.info("pdf_safety_scan_ms=%d active_content=%s", int((time.perf_counter() - scan_started) * 1000), report.has_active_or_embedded_content)
        security_payload = {"original_report": report_to_safe_dict(report)}
        if report.has_active_or_embedded_content:
            if not safe_pdf_flattening_enabled():
                raise PDFValidationError("PDF contains active or embedded content")
            flatten_started = time.perf_counter()
            safe_result = make_image_only_pdf(content)
            LOGGER.info("pdf_safe_flatten_ms=%d pages=%s", int((time.perf_counter() - flatten_started) * 1000), safe_result.safe_report.page_count)
            quarantine_dir = _uploads_dir() / "quarantine"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine_path = quarantine_dir / f"{uuid.uuid4()}_original.pdf"
            quarantine_path.write_bytes(content)
            content = safe_result.safe_pdf_bytes
            upload_notices.append(PDF_ACTIVE_CONTENT_STRIPPED_NOTICE)
            security_payload = {
                "safe_mode": "image_only_pdf",
                "notice_codes": upload_notices,
                "original_report": report_to_safe_dict(safe_result.original_report),
                "safe_report": report_to_safe_dict(safe_result.safe_report),
                "original_quarantined": True,
                "quarantine_filename": quarantine_path.name,
            }
    except PDFValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    safe_filename = f"{uuid.uuid4()}.pdf"
    file_path = _uploads_dir() / safe_filename
    file_path.write_bytes(content)
    if upload_notices:
        write_pdf_security_sidecar(file_path, security_payload)

    upload_token.is_used = True  # type: ignore
    upload_token.used_at = datetime.utcnow()  # type: ignore
    workflow_repository.transition_state(
        db,
        str(session.id),
        SessionState.UPLOADED_PENDING_REVIEW,
        extra_values={
            "filename": file.filename,
            "file_path": str(file_path),
            "uploaded_at": datetime.utcnow(),
            "worker_phase": None,
            "reason_codes": upload_notices,
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
            "agent_document_understanding_payload": None,
            "agent_credential_candidates_payload": None,
            "agent_route_recommendations_payload": None,
            "agent_explanations_payload": None,
            "agent_run_summary_payload": None,
            "agent_run_status": "NOT_STARTED",
            "agent_run_error": None,
            "provider_execution_traces_payload": None,
            "provider_execution_status": "NOT_STARTED",
            "provider_execution_error": None,
            "provider_operating_mode": None,
            "demo_profile_key": None,
            "execution_environment_label": None,
            "provider_transition_notes": None,
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

    return UploadResponse(
        message="File uploaded securely",
        filename=safe_filename,
        session_id=str(session.id),
        status=session.status,
        notices=normalize_notices(upload_notices),
    )


@router.options("/sessions/{session_id}/document")
def options_session_document(session_id: str):
    """Handle CORS preflight requests for document endpoint"""
    headers = {
        "Access-Control-Allow-Origin": "http://localhost:5173",
        "Access-Control-Allow-Methods": "GET, OPTIONS, HEAD",
        "Access-Control-Allow-Headers": "content-type, authorization",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Max-Age": "3600",
    }
    return Response(status_code=200, headers=headers)


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

    def iterfile():
        with open(file_path, mode="rb") as file_like:
            yield from file_like

    headers = {
        "Access-Control-Allow-Origin": "http://localhost:5173",
        "Access-Control-Allow-Credentials": "true",
        "Content-Disposition": f'attachment; filename="{session.filename or file_path.name}"',
    }
    
    return StreamingResponse(
        iterfile(),
        media_type="application/pdf",
        headers=headers,
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
