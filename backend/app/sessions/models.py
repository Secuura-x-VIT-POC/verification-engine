from sqlalchemy import Column, String, Boolean
from app.db.database import Base
import uuid

class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, default="CREATED")
    user_id = Column(String)

class UploadToken(Base):
    __tablename__ = "upload_tokens"
    token = Column(String, primary_key=True)
    session_id = Column(String)
    is_used = Column(Boolean, default=False)
