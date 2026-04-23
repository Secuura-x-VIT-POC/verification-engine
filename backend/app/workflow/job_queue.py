from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, update

from ..db.database import Base


JOB_STATUS_PENDING = "PENDING"
JOB_STATUS_PROCESSING = "PROCESSING"
JOB_STATUS_DONE = "DONE"
JOB_STATUS_FAILED = "FAILED"
JOB_STATUS_SKIPPED = "SKIPPED"

ACTIVE_JOB_STATUSES = {
    JOB_STATUS_PENDING,
    JOB_STATUS_PROCESSING,
}


class VerificationJob(Base):
    __tablename__ = "verification_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("verification_sessions.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default=JOB_STATUS_PENDING, index=True)
    worker_id = Column(String, nullable=True, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)


def enqueue_job(conn, session_id: str) -> VerificationJob:
    existing = (
        conn.query(VerificationJob)
        .filter(VerificationJob.session_id == session_id)
        .filter(VerificationJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(VerificationJob.created_at.asc())
        .first()
    )
    if existing is not None:
        return existing

    job = VerificationJob(session_id=session_id, status=JOB_STATUS_PENDING)
    conn.add(job)
    conn.commit()
    conn.refresh(job)
    return job


def dequeue_job(conn, worker_id: str) -> VerificationJob | None:
    job = (
        conn.query(VerificationJob)
        .filter(VerificationJob.status == JOB_STATUS_PENDING)
        .order_by(VerificationJob.created_at.asc())
        .first()
    )
    if job is None:
        return None

    now = datetime.utcnow()
    result = conn.execute(
        update(VerificationJob)
        .where(VerificationJob.id == job.id)
        .where(VerificationJob.status == JOB_STATUS_PENDING)
        .values(
            status=JOB_STATUS_PROCESSING,
            worker_id=worker_id,
            attempts=VerificationJob.attempts + 1,
            started_at=job.started_at or now,
            updated_at=now,
            heartbeat_at=now,
        )
    )
    if not result.rowcount:
        conn.rollback()
        return None

    conn.commit()
    conn.refresh(job)
    return job


def mark_job_done(conn, job_id: str) -> None:
    _mark_terminal(conn, job_id, JOB_STATUS_DONE, None)


def mark_job_failed(conn, job_id: str, error_message: str) -> None:
    _mark_terminal(conn, job_id, JOB_STATUS_FAILED, error_message)


def mark_job_skipped(conn, job_id: str, error_message: str) -> None:
    _mark_terminal(conn, job_id, JOB_STATUS_SKIPPED, error_message)


def update_job_heartbeat(conn, job_id: str, worker_id: str) -> bool:
    result = conn.execute(
        update(VerificationJob)
        .where(VerificationJob.id == job_id)
        .where(VerificationJob.worker_id == worker_id)
        .where(VerificationJob.status == JOB_STATUS_PROCESSING)
        .values(heartbeat_at=datetime.utcnow(), updated_at=datetime.utcnow())
    )
    conn.commit()
    return bool(result.rowcount)


def mark_stale_processing_jobs_failed(conn, timeout_seconds: int = 300) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
    result = conn.execute(
        update(VerificationJob)
        .where(VerificationJob.status == JOB_STATUS_PROCESSING)
        .where(VerificationJob.heartbeat_at.is_not(None))
        .where(VerificationJob.heartbeat_at < cutoff)
        .values(
            status=JOB_STATUS_FAILED,
            error_message="Worker heartbeat expired",
            completed_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    conn.commit()
    return result.rowcount or 0


def _mark_terminal(conn, job_id: str, status: str, error_message: str | None) -> None:
    conn.execute(
        update(VerificationJob)
        .where(VerificationJob.id == job_id)
        .values(
            status=status,
            error_message=error_message,
            completed_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            heartbeat_at=None,
        )
    )
    conn.commit()
