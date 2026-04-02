from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from ..sessions.models import PurgeTrackingRecord


def start_cleanup(db: DbSession, session_id: str) -> PurgeTrackingRecord:
    record = PurgeTrackingRecord(
        session_id=session_id,
        purge_status="IN_PROGRESS",
        started_at=datetime.utcnow(),
    )
    db.add(record)
    db.flush()
    return record


def complete_cleanup(db: DbSession, session_id: str) -> PurgeTrackingRecord | None:
    record = (
        db.query(PurgeTrackingRecord)
        .filter(PurgeTrackingRecord.session_id == session_id)
        .order_by(PurgeTrackingRecord.started_at.desc())
        .first()
    )
    if record is not None:
        record.purge_status = "COMPLETED"
        record.completed_at = datetime.utcnow()
        record.error_message = None
        db.flush()
    return record


def fail_cleanup(db: DbSession, session_id: str, error: str) -> PurgeTrackingRecord | None:
    record = (
        db.query(PurgeTrackingRecord)
        .filter(PurgeTrackingRecord.session_id == session_id)
        .order_by(PurgeTrackingRecord.started_at.desc())
        .first()
    )
    if record is not None:
        record.purge_status = "FAILED"
        record.error_message = error
        record.completed_at = datetime.utcnow()
        db.flush()
    return record
