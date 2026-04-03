from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..demo_profiles import DemoProfileSummary, build_demo_profile_summary, resolve_demo_profile_key
from .contracts import (
    OUTBOUND_MODE_DISABLED,
    OUTBOUND_MODE_HTTP_JSON,
    OUTBOUND_MODE_LOCAL_ONLY,
    PROVIDER_EXECUTION_STATUS_FAILED,
    PROVIDER_EXECUTION_STATUS_NOT_STARTED,
    PROVIDER_EXECUTION_STATUS_READY,
    PROVIDER_OPERATING_MODE_DEMO_MOCK,
    PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
    PROVIDER_OPERATING_MODE_LIVE_DISABLED,
    PROVIDER_TECHNICAL_STATUS_FAILED,
    ProviderExecutionTrace,
    ProviderExecutionTraceCollection,
    SessionProviderOperatingMode,
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
    def __init__(
        self,
        *,
        registry: ProviderRegistry | None = None,
        operating_context: SessionProviderOperatingMode | None = None,
    ):
        self.registry = registry or build_default_provider_registry()
        self.policy = load_provider_runtime_policy()
        self.operating_context = operating_context or _build_provider_operating_mode_snapshot(
            session_id="",
            workflow_state="UNKNOWN",
            document_type="unknown",
            policy=self.policy,
            explicit_mode=None,
            explicit_demo_profile_key=None,
            explicit_environment_label=None,
            explicit_transition_notes=None,
        )
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
            metadata={
                "category": category,
                "document_type": input_payload.get("document_type"),
                "verifier_label": verifier_label,
                "provider_operating_mode": self.operating_context.provider_operating_mode,
                "demo_profile_key": self.operating_context.demo_profile_key,
                "execution_environment_label": self.operating_context.execution_environment_label,
                "provider_transition_notes": list(self.operating_context.provider_transition_notes),
            },
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
            provider_label=provider.provider_label,
            verifier_key=verifier_key,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            technical_status=response.technical_status,
            redaction_applied=redaction_applied,
            outbound_mode=_resolve_trace_outbound_mode(
                provider_key=provider.provider_key,
                response=response,
            ),
            retry_count=max(int((response.response_summary or {}).get("retry_count", 0)), 0),
            error_summary=error_summary,
            http_status=response.http_status,
            response_summary=dict(response.response_summary or {}),
            fallback_used=False,
            provider_operating_mode=response.operating_mode or self.operating_context.provider_operating_mode,
            demo_profile_key=response.demo_profile_key or self.operating_context.demo_profile_key,
            execution_environment_label=(
                response.execution_environment_label
                or self.operating_context.execution_environment_label
            ),
            transition_notes=list(response.transition_notes or self.operating_context.provider_transition_notes),
            is_mock_result=response.is_mock_result,
            is_demo_result=response.is_demo_result,
            is_live_result=response.is_live_result,
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
    provider_operating_mode=_UNSET,
    demo_profile_key=_UNSET,
    execution_environment_label=_UNSET,
    provider_transition_notes=_UNSET,
) -> None:
    if provider_execution_traces is not _UNSET:
        session.provider_execution_traces_payload = _dump_model(provider_execution_traces)
    if provider_execution_status is not _UNSET:
        session.provider_execution_status = provider_execution_status
    if provider_execution_error is not _UNSET:
        session.provider_execution_error = provider_execution_error
    if provider_operating_mode is not _UNSET and hasattr(session, "provider_operating_mode"):
        session.provider_operating_mode = provider_operating_mode
    if demo_profile_key is not _UNSET and hasattr(session, "demo_profile_key"):
        session.demo_profile_key = demo_profile_key
    if execution_environment_label is not _UNSET and hasattr(session, "execution_environment_label"):
        session.execution_environment_label = execution_environment_label
    if provider_transition_notes is not _UNSET and hasattr(session, "provider_transition_notes"):
        session.provider_transition_notes = provider_transition_notes


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
    operating_mode = get_provider_operating_mode_for_session(session)
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
        provider_operating_mode=operating_mode.provider_operating_mode,
        execution_environment_label=operating_mode.execution_environment_label,
        demo_profile_key=operating_mode.demo_profile_key,
        provider_transition_notes=list(operating_mode.provider_transition_notes),
        live_provider_enabled=operating_mode.live_provider_enabled,
        preferred_provider_rail=operating_mode.preferred_provider_rail,
        fallback_policy=operating_mode.fallback_policy,
        manual_review_policy=operating_mode.manual_review_policy,
    )


def get_provider_capabilities_for_session(session):
    registry = build_default_provider_registry()
    return registry.capability_collection(session.id)


def get_provider_operating_mode_for_session(session) -> SessionProviderOperatingMode:
    policy = load_provider_runtime_policy()
    return _build_provider_operating_mode_snapshot(
        session_id=session.id,
        workflow_state=session.status,
        document_type=_resolve_session_document_type(session),
        policy=policy,
        explicit_mode=getattr(session, "provider_operating_mode", None),
        explicit_demo_profile_key=getattr(session, "demo_profile_key", None),
        explicit_environment_label=getattr(session, "execution_environment_label", None),
        explicit_transition_notes=getattr(session, "provider_transition_notes", None),
    )


def get_demo_profile_for_session(session) -> DemoProfileSummary:
    operating_mode = get_provider_operating_mode_for_session(session)
    if operating_mode.provider_operating_mode != PROVIDER_OPERATING_MODE_DEMO_MOCK:
        return DemoProfileSummary(
            session_id=session.id,
            profile_key=None,
            profile_label="No seeded demo profile",
            description="This session is not running in demo-mock provider mode.",
            scenario_family="none",
            provider_operating_mode=operating_mode.provider_operating_mode,
            seeded=False,
            notes=list(operating_mode.provider_transition_notes),
        )
    return build_demo_profile_summary(
        session_id=session.id,
        provider_operating_mode=operating_mode.provider_operating_mode,
        document_type=_resolve_session_document_type(session),
        explicit_key=operating_mode.demo_profile_key,
    )


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


def _build_provider_operating_mode_snapshot(
    *,
    session_id: str,
    workflow_state: str,
    document_type: str,
    policy,
    explicit_mode: Any,
    explicit_demo_profile_key: Any,
    explicit_environment_label: Any,
    explicit_transition_notes: Any,
) -> SessionProviderOperatingMode:
    transition = policy.transition_config
    provider_operating_mode = str(explicit_mode or transition.provider_operating_mode or PROVIDER_OPERATING_MODE_LIVE_DISABLED)
    demo_profile_key = explicit_demo_profile_key or transition.demo_profile_key
    if provider_operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
        demo_profile_key = resolve_demo_profile_key(
            document_type=document_type,
            explicit_key=demo_profile_key,
        )
    else:
        demo_profile_key = str(demo_profile_key).strip() or None if demo_profile_key else None

    return SessionProviderOperatingMode(
        session_id=session_id,
        workflow_state=workflow_state,
        provider_operating_mode=provider_operating_mode,
        execution_environment_label=(
            str(explicit_environment_label or transition.execution_environment_label or "Local environment")
        ),
        demo_profile_key=demo_profile_key,
        preferred_provider_rail=transition.preferred_provider_rail,
        enabled_provider_modes=list(transition.enabled_provider_modes or [provider_operating_mode]),
        live_provider_enabled=bool(transition.live_provider_enabled),
        fallback_policy=transition.fallback_policy,
        manual_review_policy=transition.manual_review_policy,
        provider_transition_notes=_resolve_transition_notes(
            operating_mode=provider_operating_mode,
            transition_notes=explicit_transition_notes,
            default_notes=transition.provider_transition_notes,
            demo_profile_key=demo_profile_key,
        ),
    )


def _resolve_transition_notes(
    *,
    operating_mode: str,
    transition_notes: Any,
    default_notes: list[str] | None,
    demo_profile_key: str | None,
) -> list[str]:
    persisted_notes = _as_string_list(transition_notes)
    if persisted_notes:
        return persisted_notes

    notes = list(default_notes or [])
    if operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK and demo_profile_key:
        notes.append(f"Seeded demo profile '{demo_profile_key}' is active for this session.")
    if operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        notes.append("Live outbound verification remains bounded by allowlists, redaction, and timeout budgets.")
    return _dedupe_notes(notes)


def _resolve_session_document_type(session) -> str:
    document_profile_payload = getattr(session, "document_profile_payload", None)
    if isinstance(document_profile_payload, dict):
        document_type = str(document_profile_payload.get("document_type") or "").strip()
        if document_type:
            return document_type
    extraction_payload = getattr(session, "extraction_payload", None)
    if isinstance(extraction_payload, dict):
        document_type = str(extraction_payload.get("document_type") or "").strip()
        if document_type:
            return document_type
    return "unknown"


def _resolve_trace_outbound_mode(*, provider_key: str, response) -> str:
    response_summary = dict(getattr(response, "response_summary", {}) or {})
    explicit_mode = str(response_summary.get("outbound_mode") or "").strip()
    if explicit_mode:
        return explicit_mode
    if provider_key == "local_mock":
        return OUTBOUND_MODE_LOCAL_ONLY
    if getattr(response, "is_demo_result", False):
        return OUTBOUND_MODE_LOCAL_ONLY
    return OUTBOUND_MODE_HTTP_JSON


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe_notes(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


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
