import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.sessions.models import Session as SessionModel, UploadToken
from app.auth.routes import get_current_user

import os

router = APIRouter()

@router.post("/sessions")
def create_session(
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user)
):
    new_session = SessionModel(user_id=user)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return {"session_id": new_session.id, "status": new_session.status}


@router.post("/sessions/{session_id}/upload-token")
def generate_upload_token(
    session_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user)
):
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user:
        raise HTTPException(status_code=403, detail="Not authorized")

    token = str(uuid.uuid4())
    upload_token = UploadToken(
        token=token,
        session_id=session_id,
        is_used=False
    )
    db.add(upload_token)
    db.commit()
    return {"upload_token": token}


@router.post("/upload")
def upload_file(
    token: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user)
):
    upload_token = db.query(UploadToken).filter(UploadToken.token == token).first()
    if not upload_token:
        raise HTTPException(status_code=404, detail="Invalid token")
    if upload_token.is_used:
        raise HTTPException(status_code=400, detail="Token already used")

    session = db.query(SessionModel).filter(
        SessionModel.id == upload_token.session_id
    ).first()

    if session.user_id != user:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF allowed")

    content = file.file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")

    os.makedirs("uploads", exist_ok=True)
    safe_filename = f"{uuid.uuid4()}.pdf"
    file_path = f"uploads/{safe_filename}"

    with open(file_path, "wb") as f:
        f.write(content)

    upload_token.is_used = True
    db.commit()

    return {
        "message": "File uploaded securely",
        "filename": safe_filename
    }