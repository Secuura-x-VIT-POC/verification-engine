from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update

from ..sessions.constants import SessionState
from ..sessions.models import Session as SessionModel
from .state_machine import InvalidStateTransitionError, validate_transition

LOGGER = logging.getLogger(__name__)

PENDING_REVIEW_STATE = SessionState.UPLOADED_PENDING_REVIEW
VERIFYING_STATE = SessionState.VERIFYING
LEASE_ACQUIRABLE_STATES = {
    PENDING_REVIEW_STATE,
    SessionState.FAILED_RETRIABLE,
}


class StateTransitionConflictError(RuntimeError):
    pass


def get_session_state_and_version(conn, session_id: str) -> dict[str, object] | None:
    row = conn.execute(
        select(SessionModel.status, SessionModel.version).where(SessionModel.id == session_id)
    ).first()
    if row is None:
        return None

    return {
        "state": row.status,
        "version": row.version,
    }


def get_session_state(conn, session_id: str) -> str | None:
    session = get_session_state_and_version(conn, session_id)
    if session is None:
        return None
    return str(session["state"])


def transition_state(
    conn,
    session_id: str,
    new_state: str,
    *,
    extra_values: dict | None = None,
    require_lease_id: str | None = None,
    require_null_lease: bool = False,
) -> str:
    current_state = get_session_state(conn, session_id)
    if current_state is None:
        raise StateTransitionConflictError(f"Session not found: {session_id}")

    _validate_transition_or_raise(
        session_id=session_id,
        current_state=current_state,
        new_state=new_state,
    )

    values = {
        "status": new_state,
        "updated_at": datetime.utcnow(),
    }
    if extra_values:
        values.update(extra_values)

    statement = (
        update(SessionModel)
        .where(SessionModel.id == session_id)
        .where(SessionModel.status == current_state)
        .values(**values)
        .returning(SessionModel.id)
    )

    if require_null_lease:
        statement = statement.where(SessionModel.lease_id.is_(None))
    if require_lease_id is not None:
        statement = statement.where(SessionModel.lease_id == require_lease_id)

    result = conn.execute(statement)
    updated_session_id = result.scalar_one_or_none()
    if updated_session_id is None:
        raise StateTransitionConflictError(
            f"Atomic state transition failed for session {session_id}: {current_state} -> {new_state}"
        )

    LOGGER.info(
        "STATE_TRANSITION: %s → %s session_id=%s",
        current_state,
        new_state,
        session_id,
    )
    return current_state


def acquire_lease(conn, session_id: str, worker_id: str) -> bool:
    session = get_session_state_and_version(conn, session_id)
    if session is None or session["state"] not in LEASE_ACQUIRABLE_STATES:
        return False

    try:
        transition_state(
            conn,
            session_id,
            VERIFYING_STATE,
            extra_values={
                "lease_id": worker_id,
                "lease_holder_id": worker_id,
                "lease_acquired_at": datetime.utcnow(),
            },
            require_null_lease=True,
        )
    except StateTransitionConflictError:
        return False

    return True


def update_worker_phase(conn, session_id: str, worker_id: str, worker_phase: str) -> None:
    conn.execute(
        update(SessionModel)
        .where(SessionModel.id == session_id)
        .where(SessionModel.lease_id == worker_id)
        .values(
            worker_phase=worker_phase,
            updated_at=datetime.utcnow(),
        )
    )


def update_heartbeat(conn, session_id: str, worker_id: str) -> int:
    result = conn.execute(
        update(SessionModel)
        .where(SessionModel.id == session_id)
        .where(SessionModel.lease_id == worker_id)
        .values(
            heartbeat_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    return result.rowcount or 0


def mark_stale_sessions(conn, timeout_seconds: int = 60) -> int:
    _validate_transition_or_raise(
        session_id="bulk-stale-session-scan",
        current_state=VERIFYING_STATE,
        new_state=SessionState.ABANDONED_VERIFYING,
    )

    cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
    result = conn.execute(
        update(SessionModel)
        .where(SessionModel.status == VERIFYING_STATE)
        .where(SessionModel.heartbeat_at.is_not(None))
        .where(SessionModel.heartbeat_at < cutoff)
        .values(
            status=SessionState.ABANDONED_VERIFYING,
            lease_id=None,
            lease_holder_id=None,
            lease_acquired_at=None,
            updated_at=datetime.utcnow(),
        )
    )

    updated_rows = result.rowcount or 0
    if updated_rows:
        LOGGER.info(
            "STATE_TRANSITION: %s → %s count=%s",
            VERIFYING_STATE,
            SessionState.ABANDONED_VERIFYING,
            updated_rows,
        )
    return updated_rows


def complete_processing(
    conn,
    session_id: str,
    outcome_state: str,
    outcome: str,
    reason_codes: list[str],
    connector_ids: list[str],
    *,
    extra_values: dict | None = None,
) -> None:
    values = {
        "trust_outcome": outcome,
        "reason_codes": reason_codes,
        "connector_ids": connector_ids,
        "worker_phase": "COMPLETED",
        "lease_id": None,
        "lease_holder_id": None,
        "lease_acquired_at": None,
        "heartbeat_at": None,
    }
    if extra_values:
        values.update(extra_values)

    transition_state(
        conn,
        session_id,
        outcome_state,
        extra_values=values,
    )


def fail_processing(
    conn,
    session_id: str,
    failure_state: str,
    reason_codes: list[str],
    *,
    extra_values: dict | None = None,
) -> None:
    values = {
        "worker_phase": "FAILED",
        "trust_outcome": None,
        "reason_codes": reason_codes,
        "connector_ids": [],
        "lease_id": None,
        "lease_holder_id": None,
        "lease_acquired_at": None,
        "heartbeat_at": None,
    }
    if extra_values:
        values.update(extra_values)

    transition_state(
        conn,
        session_id,
        failure_state,
        extra_values=values,
    )


def _validate_transition_or_raise(*, session_id: str, current_state: str, new_state: str) -> None:
    try:
        validate_transition(current_state, new_state)
    except InvalidStateTransitionError:
        LOGGER.warning(
            "INVALID_TRANSITION_BLOCKED session_id=%s current_state=%s new_state=%s",
            session_id,
            current_state,
            new_state,
        )
        raise
