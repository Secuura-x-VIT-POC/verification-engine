from __future__ import annotations

from ..workflow.job_queue import enqueue_job


def trigger_processing(conn, session_id: str, worker_id: str, max_retries=3):
    """
    Enqueues verification work. A separate worker must acquire the strict
    single-session lease before processing.
    Returns:
        - "STARTED" -> work is queued or already pending
        - "NO_OP" -> reserved for future queue rejection semantics
        - "FAILED" -> unexpected issue
    """

    del worker_id
    del max_retries

    try:
        enqueue_job(conn, session_id)
        return "STARTED"
    except Exception:
        _safe_rollback(conn)
        return "FAILED"


def _safe_rollback(conn) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()
