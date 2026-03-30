from __future__ import annotations

PENDING_REVIEW_STATE = "UPLOADED_PENDING_REVIEW"
VERIFYING_STATE = "VERIFYING"


def get_session_state_and_version(conn, session_id: str) -> dict[str, object] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT state, version
            FROM audit.sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    state, version = row
    return {"state": state, "version": version}


def acquire_lease(conn, session_id: str, worker_id: str, version: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit.sessions
            SET
                state = %s,
                lease_holder_id = %s,
                lease_acquired_at = NOW(),
                heartbeat_at = NOW(),
                version = version + 1,
                updated_at = NOW()
            WHERE
                session_id = %s
                AND state = %s
                AND version = %s
            RETURNING session_id
            """,
            (
                VERIFYING_STATE,
                worker_id,
                session_id,
                PENDING_REVIEW_STATE,
                version,
            ),
        )
        return cur.fetchone() is not None


def update_worker_phase(conn, session_id: str, worker_id: str, worker_phase: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit.sessions
            SET
                worker_phase = %s,
                updated_at = NOW()
            WHERE
                session_id = %s
                AND lease_holder_id = %s
            """,
            (worker_phase, session_id, worker_id),
        )


def update_heartbeat(conn, session_id: str, worker_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit.sessions
            SET
                heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE
                session_id = %s
                AND lease_holder_id = %s
            """,
            (session_id, worker_id),
        )


def mark_stale_sessions(conn, timeout_seconds: int = 60) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit.sessions
            SET
                state = 'ABANDONED_VERIFYING',
                lease_holder_id = NULL,
                updated_at = NOW()
            WHERE
                state = %s
                AND heartbeat_at < NOW() - (%s * INTERVAL '1 second')
            """,
            (VERIFYING_STATE, timeout_seconds),
        )
        return cur.rowcount


def complete_processing(
    conn,
    session_id: str,
    outcome_state: str,
    outcome: str,
    reason_codes: list[str],
    connector_ids: list[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit.sessions
            SET
                state = %s,
                trust_outcome = %s,
                reason_codes = %s,
                connector_ids = %s,
                worker_phase = 'COMPLETED',
                lease_holder_id = NULL,
                updated_at = NOW()
            WHERE session_id = %s
            """,
            (
                outcome_state,
                outcome,
                reason_codes,
                connector_ids,
                session_id,
            ),
        )
