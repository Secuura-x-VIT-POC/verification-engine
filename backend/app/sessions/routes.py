from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth.routes import get_current_user
from ..db.database import get_db
from ..security.pdf_validator import PDFValidationError, validate_pdf
from .constants import SessionState
from .models import Session as SessionModel
from .models import UploadToken


router = APIRouter(tags=["sessions"])


def _uploads_dir() -> Path:
    upload_dir = Path("uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@router.post("/sessions")
def create_session(
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict[str, str]:
    new_session = SessionModel(user_id=user)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    return {"session_id": new_session.id, "status": new_session.status}


@router.post("/sessions/{session_id}/upload-token")
def generate_upload_token(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
) -> dict[str, str]:
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user:
        raise HTTPException(status_code=403, detail="Not authorized")

    upload_token = UploadToken(
        token=str(uuid.uuid4()),
        session_id=session_id,
        is_used=False,
    )
    db.add(upload_token)
    db.commit()
    db.refresh(upload_token)

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
    if not upload_token:
        raise HTTPException(status_code=404, detail="Invalid token")
    if upload_token.is_used:
        raise HTTPException(status_code=409, detail="Token already used")
    if upload_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")

    session = db.query(SessionModel).filter(SessionModel.id == upload_token.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF allowed")

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
    session.file_path = str(file_path)
    session.status = SessionState.UPLOADED
    db.commit()

    return {
        "message": "File uploaded securely",
        "filename": safe_filename,
        "session_id": session.id,
        "status": session.status,
    }
