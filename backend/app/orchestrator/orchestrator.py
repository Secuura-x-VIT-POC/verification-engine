from __future__ import annotations

from ..workflow import service


def trigger_processing(conn, session_id: str, worker_id: str, max_retries=3):
    """
    Attempts to acquire a strict single-worker lease before processing.
    Returns:
        - "STARTED" -> this worker owns execution
        - "NO_OP" -> another worker already owns the lease
        - "FAILED" -> unexpected issue
    """

    del max_retries

    try:
        if service.acquire_lease(conn, session_id, worker_id):
            return "STARTED"
        return "NO_OP"
    except Exception:
        _safe_rollback(conn)
        return "FAILED"


def _safe_rollback(conn) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()
