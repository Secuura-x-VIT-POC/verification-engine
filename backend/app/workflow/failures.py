from __future__ import annotations

from dataclasses import dataclass

from ..sessions.constants import SessionState


@dataclass(frozen=True)
class FailureClassification:
    error_type: str
    retriable: bool
    state: str
    reason_codes: list[str]


class WorkflowProcessingError(RuntimeError):
    def __init__(self, error_type: str, message: str | None = None, context: dict | None = None) -> None:
        super().__init__(message or error_type)
        self.error_type = error_type
        self.context = context or {}


def classify_failure(error_type: str, context: dict | None = None) -> FailureClassification:
    resolved_context = context or {}
    assurance_class = str(resolved_context.get("assurance_class", "")).upper()

    if error_type == "connector_timeout" and assurance_class == "HIGH":
        return FailureClassification(
            error_type=error_type,
            retriable=False,
            state=SessionState.FAILED_PURGED,
            reason_codes=["CONNECTOR_TIMEOUT_REQUIRED"],
        )

    if error_type == "transient_connector_error":
        return FailureClassification(
            error_type=error_type,
            retriable=True,
            state=SessionState.FAILED_RETRIABLE,
            reason_codes=["TRANSIENT_CONNECTOR_ERROR"],
        )

    if error_type == "audit_store_failure":
        return FailureClassification(
            error_type=error_type,
            retriable=True,
            state=SessionState.FAILED_RETRIABLE,
            reason_codes=["AUDIT_STORE_FAILURE"],
        )

    if error_type == "extraction_crash":
        return FailureClassification(
            error_type=error_type,
            retriable=True,
            state=SessionState.FAILED_RETRIABLE,
            reason_codes=["EXTRACTION_CRASH"],
        )

    if error_type in {"malformed_document", "document_missing"}:
        return FailureClassification(
            error_type=error_type,
            retriable=False,
            state=SessionState.FAILED_PURGED,
            reason_codes=["MALFORMED_DOCUMENT" if error_type == "malformed_document" else "DOCUMENT_NOT_FOUND"],
        )

    return FailureClassification(
        error_type=error_type,
        retriable=True,
        state=SessionState.FAILED_RETRIABLE,
        reason_codes=["WORKFLOW_EXECUTION_FAILED"],
    )
