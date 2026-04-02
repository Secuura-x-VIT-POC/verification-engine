from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String

from ..db.database import Base
from .constants import SessionState


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, default=SessionState.CREATED, nullable=False)
    user_id = Column(String, nullable=False)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UploadToken(Base):
    __tablename__ = "upload_tokens"

    token = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    is_used = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10), nullable=False)
    used_at = Column(DateTime, nullable=True)
