import time

from ..workflow import repository


def trigger_processing(conn, session_id: str, worker_id: str, max_retries=3):
    """
    Attempts to acquire lease and start processing.
    Returns:
        - "STARTED" -> this worker owns execution
        - "NO_OP" -> another worker already started
        - "FAILED" -> unexpected issue
    """

    for attempt in range(max_retries):
        try:
            session = repository.get_session_state_and_version(conn, session_id)

            if not session:
                _safe_rollback(conn)
                return "FAILED"

            if session["state"] != repository.PENDING_REVIEW_STATE:
                _safe_rollback(conn)
                return "NO_OP"

            if repository.acquire_lease(
                conn,
                session_id,
                worker_id,
                session["version"],
            ):
                conn.commit()
                return "STARTED"

            _safe_rollback(conn)
            time.sleep(0.05 * (attempt + 1))

        except Exception:
            _safe_rollback(conn)
            return "FAILED"

    return "NO_OP"


def _safe_rollback(conn) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()
