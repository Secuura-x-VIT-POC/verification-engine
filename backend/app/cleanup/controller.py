from sqlalchemy import create_engine, text
import os
import uuid
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)


def start_cleanup(session_id: str):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO audit.purge_tracking (
                purge_id,
                session_id,
                purge_status,
                started_at
            ) VALUES (
                :purge_id,
                :session_id,
                'IN_PROGRESS',
                :started_at
            )
        """), {
            "purge_id": str(uuid.uuid4()),
            "session_id": session_id,
            "started_at": datetime.utcnow()
        })


def complete_cleanup(session_id: str):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE audit.purge_tracking
            SET purge_status = 'COMPLETED',
                completed_at = :completed_at
            WHERE session_id = :session_id
        """), {
            "session_id": session_id,
            "completed_at": datetime.utcnow()
        })


def fail_cleanup(session_id: str, error: str):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE audit.purge_tracking
            SET purge_status = 'FAILED',
                error_message = :error
            WHERE session_id = :session_id
        """), {
            "session_id": session_id,
            "error": error
        })