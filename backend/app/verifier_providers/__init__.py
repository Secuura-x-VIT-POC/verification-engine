from __future__ import annotations

from importlib import import_module

from .contracts import (
    OUTBOUND_MODE_DISABLED,
    OUTBOUND_MODE_HTTP_JSON,
    OUTBOUND_MODE_LOCAL_ONLY,
    PROVIDER_EXECUTION_STATUS_FAILED,
    PROVIDER_EXECUTION_STATUS_NOT_STARTED,
    PROVIDER_EXECUTION_STATUS_READY,
    PROVIDER_EXECUTION_STATUS_RUNNING,
    PROVIDER_OPERATING_MODE_DEMO_MOCK,
    PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
    PROVIDER_OPERATING_MODE_LIVE_DISABLED,
    PROVIDER_OPERATING_MODE_LOCAL_MOCK,
    PROVIDER_OPERATING_MODE_MANUAL_ONLY,
    PROVIDER_TECHNICAL_STATUS_BLOCKED,
    PROVIDER_TECHNICAL_STATUS_DISABLED,
    PROVIDER_TECHNICAL_STATUS_FAILED,
    PROVIDER_TECHNICAL_STATUS_SKIPPED,
    PROVIDER_TECHNICAL_STATUS_SUCCESS,
    PROVIDER_TECHNICAL_STATUS_TIMEOUT,
    PROVIDER_TECHNICAL_STATUS_UNCONFIGURED,
    ProviderCapability,
    ProviderCapabilityCollection,
    ProviderExecutionTrace,
    ProviderExecutionTraceCollection,
    ProviderRequest,
    ProviderResponse,
    ProviderTransitionConfig,
    SessionProviderOperatingMode,
    SessionProviderExecutionStatus,
)


_LAZY_IMPORTS = {
    "ProviderExecutionRuntime": (".service", "ProviderExecutionRuntime"),
    "ProviderRegistry": (".registry", "ProviderRegistry"),
    "SafeHttpJsonClient": (".http_client", "SafeHttpJsonClient"),
    "build_default_provider_registry": (".registry", "build_default_provider_registry"),
    "get_provider_capabilities_for_session": (".service", "get_provider_capabilities_for_session"),
    "get_demo_profile_for_session": (".service", "get_demo_profile_for_session"),
    "get_provider_operating_mode_for_session": (".service", "get_provider_operating_mode_for_session"),
    "get_provider_execution_status_for_session": (".service", "get_provider_execution_status_for_session"),
    "get_provider_execution_traces_for_session": (".service", "get_provider_execution_traces_for_session"),
    "load_provider_runtime_policy": (".policies", "load_provider_runtime_policy"),
    "mark_provider_execution_failure": (".service", "mark_provider_execution_failure"),
    "persist_provider_execution_artifacts": (".service", "persist_provider_execution_artifacts"),
}


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute)
    globals()[name] = value
    return value


__all__ = [
    "OUTBOUND_MODE_DISABLED",
    "OUTBOUND_MODE_HTTP_JSON",
    "OUTBOUND_MODE_LOCAL_ONLY",
    "PROVIDER_EXECUTION_STATUS_FAILED",
    "PROVIDER_EXECUTION_STATUS_NOT_STARTED",
    "PROVIDER_EXECUTION_STATUS_READY",
    "PROVIDER_EXECUTION_STATUS_RUNNING",
    "PROVIDER_OPERATING_MODE_DEMO_MOCK",
    "PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED",
    "PROVIDER_OPERATING_MODE_LIVE_DISABLED",
    "PROVIDER_OPERATING_MODE_LOCAL_MOCK",
    "PROVIDER_OPERATING_MODE_MANUAL_ONLY",
    "PROVIDER_TECHNICAL_STATUS_BLOCKED",
    "PROVIDER_TECHNICAL_STATUS_DISABLED",
    "PROVIDER_TECHNICAL_STATUS_FAILED",
    "PROVIDER_TECHNICAL_STATUS_SKIPPED",
    "PROVIDER_TECHNICAL_STATUS_SUCCESS",
    "PROVIDER_TECHNICAL_STATUS_TIMEOUT",
    "PROVIDER_TECHNICAL_STATUS_UNCONFIGURED",
    "ProviderCapability",
    "ProviderCapabilityCollection",
    "ProviderExecutionRuntime",
    "ProviderExecutionTrace",
    "ProviderExecutionTraceCollection",
    "ProviderRegistry",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderTransitionConfig",
    "SafeHttpJsonClient",
    "SessionProviderOperatingMode",
    "SessionProviderExecutionStatus",
    "build_default_provider_registry",
    "get_demo_profile_for_session",
    "get_provider_capabilities_for_session",
    "get_provider_operating_mode_for_session",
    "get_provider_execution_status_for_session",
    "get_provider_execution_traces_for_session",
    "load_provider_runtime_policy",
    "mark_provider_execution_failure",
    "persist_provider_execution_artifacts",
]
