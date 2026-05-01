from __future__ import annotations

from ..sessions.constants import SessionState


ALLOWED_TRANSITIONS = {
    SessionState.CREATED: {SessionState.UPLOAD_PENDING},
    SessionState.UPLOAD_PENDING: {SessionState.UPLOADED_PENDING_REVIEW},
    SessionState.UPLOADED_PENDING_REVIEW: {SessionState.VERIFYING},
    SessionState.VERIFYING: {
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
        SessionState.PENDING_HUMAN_REVIEW,
        SessionState.FAILED_RETRIABLE,
        SessionState.FAILED_PURGED,
        SessionState.ABANDONED_VERIFYING,
    },
    SessionState.VERIFIED_GREEN: {SessionState.PENDING_HUMAN_REVIEW},
    SessionState.VERIFIED_AMBER: {SessionState.PENDING_HUMAN_REVIEW},
    SessionState.VERIFIED_RED: {SessionState.PENDING_HUMAN_REVIEW},
    SessionState.PENDING_HUMAN_REVIEW: {
        SessionState.HUMAN_APPROVED,
        SessionState.HUMAN_REJECTED,
        SessionState.MANUAL_REVIEW_REQUIRED,
    },
    SessionState.HUMAN_APPROVED: {SessionState.PENDING_CLEANUP},
    SessionState.HUMAN_REJECTED: {SessionState.PENDING_CLEANUP},
    SessionState.MANUAL_REVIEW_REQUIRED: {SessionState.PENDING_CLEANUP},
    SessionState.PENDING_CLEANUP: {
        SessionState.PURGE_COMPLETE,
        SessionState.FAILED_PURGED,
    },
    SessionState.FAILED_RETRIABLE: {SessionState.VERIFYING},
    SessionState.ABANDONED_VERIFYING: {
        SessionState.FAILED_RETRIABLE,
        SessionState.FAILED_PURGED,
    },
}


class InvalidStateTransitionError(RuntimeError):
    pass


def validate_transition(current_state: str, new_state: str) -> None:
    curr = current_state.strip()
    next_s = new_state.strip()

    allowed_states = ALLOWED_TRANSITIONS.get(curr, set())
    if next_s not in allowed_states:
        raise InvalidStateTransitionError(
            f"Invalid state transition: {curr} -> {next_s}"
        )
