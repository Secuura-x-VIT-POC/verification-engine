from __future__ import annotations

from ..sessions.constants import SessionState


ALLOWED_TRANSITIONS = {
    SessionState.CREATED: {SessionState.UPLOAD_PENDING},
    SessionState.UPLOAD_PENDING: {SessionState.UPLOADED_PENDING_REVIEW},
    SessionState.UPLOADED_PENDING_REVIEW: {SessionState.VERIFYING},
    SessionState.FAILED_RETRIABLE: {SessionState.VERIFYING},
    SessionState.VERIFYING: {
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
        SessionState.ABANDONED_VERIFYING,
        SessionState.FAILED_RETRIABLE,
        SessionState.FAILED_PURGED,
    },
    SessionState.ABANDONED_VERIFYING: {
        SessionState.FAILED_RETRIABLE,
        SessionState.FAILED_PURGED,
    },
    SessionState.VERIFIED_GREEN: {SessionState.PENDING_CLEANUP},
    SessionState.VERIFIED_AMBER: {SessionState.PENDING_CLEANUP},
    SessionState.VERIFIED_RED: {SessionState.PENDING_CLEANUP},
    SessionState.PENDING_CLEANUP: {
        SessionState.PURGE_COMPLETE,
        SessionState.FAILED_PURGED,
    },
}


class InvalidStateTransitionError(RuntimeError):
    pass


def validate_transition(current_state: str, new_state: str) -> None:
    allowed_states = ALLOWED_TRANSITIONS.get(current_state, set())
    if new_state not in allowed_states:
        raise InvalidStateTransitionError(
            f"Invalid state transition: {current_state} -> {new_state}"
        )
