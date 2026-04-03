from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .contracts import (
    OUTBOUND_MODE_DISABLED,
    OUTBOUND_MODE_HTTP_JSON,
    OUTBOUND_MODE_LOCAL_ONLY,
    PROVIDER_EXECUTION_STATUS_FAILED,
    PROVIDER_EXECUTION_STATUS_NOT_STARTED,
    PROVIDER_EXECUTION_STATUS_READY,
    PROVIDER_TECHNICAL_STATUS_FAILED,
    ProviderExecutionTrace,
    ProviderExecutionTraceCollection,
    SessionProviderExecutionStatus,
)
from .policies import load_provider_runtime_policy, minimize_payload
from .registry import ProviderRegistry, build_default_provider_registry


LOGGER = logging.getLogger(__name__)
_UNSET = object()


@dataclass(frozen=True)
class ProviderAttemptOutcome:
    provider_key: str
    provider_label: str
    response: Any
    trace: ProviderExecutionTrace


class ProviderExecutionRuntime:
    def __init__(self, *, registry: ProviderRegistry | None = None):
        self.registry = registry or build_default_provider_registry()
        self.policy = load_provider_runtime_policy()
        self.traces: list[ProviderExecutionTrace] = []
        self.error: str | None = None

    def attempt_verification(
        self,
        *,
        session_id: str,
        verifier_key: str,
        verifier_label: str,
        category: str,
        task_id: str,
        input_payload: dict[str, Any],
        preferred_provider_key: str | None = None,
    ) -> ProviderAttemptOutcome | None:
        provider = self.registry.find_provider(
            verifier_key=verifier_key,
            category=category,
            preferred_provider_key=preferred_provider_key,
        )
        if provider is None:
            return None

        capability = provider.get_capabilities()
        minimized_payload, redaction_applied = minimize_payload(
            input_payload,
            allow_document_upload=capability.supports_document_upload,
        )
        request = provider.prepare_request(
            session_id=session_id,
            task_id=task_id,
            verifier_key=verifier_key,
            input_payload=minimized_payload,
            redacted_payload=minimized_payload,
            timeout_ms=capability.default_timeout_ms,
            metadata={"category": category, "verifier_label": verifier_label},
        )

        started_at = datetime.utcnow()
        try:
            response = provider.execute(request)
            error_summary = None
        except Exception as exc:  # pragma: no cover - defensive
            self.error = str(exc)
            response = provider.normalize_response(
                request=request,
                payload={
                    "reason_codes": ["PROVIDER_RUNTIME_EXCEPTION"],
                    "response_summary": {"message": str(exc)[:240]},
                },
                technical_status=PROVIDER_TECHNICAL_STATUS_FAILED,
                http_status=None,
                latency_ms=0,
            )
            error_summary = str(exc)[:240]

        trace = ProviderExecutionTrace(
            request_id=request.request_id,
            provider_key=provider.provider_key,
            verifier_key=verifier_key,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            technical_status=response.technical_status,
            redaction_applied=redaction_applied,
            outbound_mode=OUTBOUND_MODE_LOCAL_ONLY if provider.provider_key == "local_mock" else OUTBOUND_MODE_HTTP_JSON,
            retry_count=max(int((response.response_summary or {}).get("retry_count", 0)), 0),
            error_summary=error_summary,
            http_status=response.http_status,
            response_summary=dict(response.response_summary or {}),
            fallback_used=False,
        )
        self.traces.append(trace)
        return ProviderAttemptOutcome(
            provider_key=provider.provider_key,
            provider_label=provider.provider_label,
            response=response,
            trace=trace,
        )

    def mark_fallback_used(self, request_id: str) -> None:
        for index, trace in enumerate(self.traces):
            if trace.request_id == request_id:
                self.traces[index] = trace.model_copy(update={"fallback_used": True})
                return

    def build_trace_collection(self, *, session_id: str, document_type: str) -> ProviderExecutionTraceCollection:
        return ProviderExecutionTraceCollection(
            session_id=session_id,
            document_type=document_type,
            traces=list(self.traces),
        )

    def infer_status(self) -> str:
        if not self.traces:
            return PROVIDER_EXECUTION_STATUS_NOT_STARTED
        if self.error:
            return PROVIDER_EXECUTION_STATUS_FAILED
        return PROVIDER_EXECUTION_STATUS_READY


def persist_provider_execution_artifacts(
    session,
    *,
    provider_execution_traces=_UNSET,
    provider_execution_status=_UNSET,
    provider_execution_error=_UNSET,
) -> None:
    if provider_execution_traces is not _UNSET:
        session.provider_execution_traces_payload = _dump_model(provider_execution_traces)
    if provider_execution_status is not _UNSET:
        session.provider_execution_status = provider_execution_status
    if provider_execution_error is not _UNSET:
        session.provider_execution_error = provider_execution_error


def mark_provider_execution_failure(session, error: Exception | str) -> None:
    error_message = str(error)
    LOGGER.warning("PROVIDER_EXECUTION_FAILED session_id=%s error=%s", session.id, error_message)
    persist_provider_execution_artifacts(
        session,
        provider_execution_status=PROVIDER_EXECUTION_STATUS_FAILED,
        provider_execution_error=error_message,
    )


def get_provider_execution_traces_for_session(session) -> ProviderExecutionTraceCollection:
    persisted = _load_model(ProviderExecutionTraceCollection, getattr(session, "provider_execution_traces_payload", None))
    if persisted is not None:
        return persisted
    return ProviderExecutionTraceCollection(
        session_id=session.id,
        document_type=str((session.extraction_payload or {}).get("document_type") or "unknown"),
        traces=[],
    )


def get_provider_execution_status_for_session(session) -> SessionProviderExecutionStatus:
    traces = get_provider_execution_traces_for_session(session)
    provider_keys_used = sorted({trace.provider_key for trace in traces.traces if trace.provider_key})
    fallback_used = any(trace.fallback_used for trace in traces.traces)
    outbound_attempted = any(trace.outbound_mode not in {OUTBOUND_MODE_DISABLED, OUTBOUND_MODE_LOCAL_ONLY} for trace in traces.traces)
    return SessionProviderExecutionStatus(
        session_id=session.id,
        workflow_state=session.status,
        provider_execution_status=_infer_provider_status(session, traces),
        provider_execution_error=getattr(session, "provider_execution_error", None),
        traces_available=bool(getattr(session, "provider_execution_traces_payload", None)) or bool(traces.traces),
        trace_count=len(traces.traces),
        provider_keys_used=provider_keys_used,
        outbound_attempted=outbound_attempted,
        fallback_used=fallback_used,
    )


def get_provider_capabilities_for_session(session):
    registry = build_default_provider_registry()
    return registry.capability_collection(session.id)


def _infer_provider_status(session, traces: ProviderExecutionTraceCollection) -> str:
    explicit = getattr(session, "provider_execution_status", None)
    if explicit and (
        str(explicit) != PROVIDER_EXECUTION_STATUS_NOT_STARTED
        or getattr(session, "provider_execution_traces_payload", None)
    ):
        return str(explicit)
    if getattr(session, "provider_execution_error", None):
        return PROVIDER_EXECUTION_STATUS_FAILED
    if traces.traces:
        return PROVIDER_EXECUTION_STATUS_READY
    return PROVIDER_EXECUTION_STATUS_NOT_STARTED


def _load_model(model_cls, payload: Any):
    if payload in (None, ""):
        return None
    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)
    except Exception:
        LOGGER.warning(
            "PROVIDER_ARTIFACT_LOAD_FAILED model=%s",
            getattr(model_cls, "__name__", str(model_cls)),
            exc_info=True,
        )
        return None


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value
