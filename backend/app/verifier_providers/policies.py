from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .contracts import (
    OUTBOUND_MODE_HTTP_JSON,
    OUTBOUND_MODE_LOCAL_ONLY,
    PROVIDER_OPERATING_MODE_DEMO_MOCK,
    PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
    PROVIDER_OPERATING_MODE_LIVE_DISABLED,
    PROVIDER_OPERATING_MODE_LOCAL_MOCK,
    PROVIDER_OPERATING_MODE_MANUAL_ONLY,
    ProviderTransitionConfig,
)


SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "document",
    "document_blob",
    "document_bytes",
    "document_content",
    "document_text",
    "file",
    "file_bytes",
    "file_content",
    "full_document",
    "full_text",
    "raw_document",
    "raw_pdf",
    "raw_text",
    "source_text",
}


@dataclass(frozen=True)
class ProviderConfig:
    provider_key: str
    provider_label: str
    enabled: bool
    base_url: str | None
    timeout_ms: int
    retry_budget: int
    outbound_mode: str
    allow_document_upload: bool
    field_lookup_preferred: bool
    require_minimization: bool
    domain_allowlist: tuple[str, ...] = ()
    api_key: str | None = None
    demo_enabled: bool = True
    operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    execution_environment_label: str = "Local environment"


@dataclass(frozen=True)
class ProviderRuntimePolicy:
    external_provider_enabled: bool
    enabled_provider_keys: tuple[str, ...]
    default_timeout_ms: int
    default_retry_budget: int
    request_size_limit_bytes: int
    response_size_limit_bytes: int
    global_domain_allowlist: tuple[str, ...] = ()
    provider_configs: dict[str, ProviderConfig] = field(default_factory=dict)
    transition_config: ProviderTransitionConfig = field(default_factory=ProviderTransitionConfig)

    def is_provider_enabled(self, provider_key: str) -> bool:
        config = self.provider_configs.get(provider_key)
        if provider_key == "local_mock":
            return self.transition_config.provider_operating_mode != PROVIDER_OPERATING_MODE_MANUAL_ONLY
        if config is None:
            return False
        if self.transition_config.provider_operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
            return config.demo_enabled and (
                not self.enabled_provider_keys or provider_key in self.enabled_provider_keys
            )
        if self.transition_config.provider_operating_mode != PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
            return False
        return (
            self.external_provider_enabled
            and config.enabled
            and bool(config.base_url)
            and provider_key in self.enabled_provider_keys
        )

    def should_register_provider(self, provider_key: str) -> bool:
        if provider_key == "local_mock":
            return self.transition_config.provider_operating_mode != PROVIDER_OPERATING_MODE_MANUAL_ONLY
        return self.is_provider_enabled(provider_key)

    def config_for(self, provider_key: str) -> ProviderConfig | None:
        return self.provider_configs.get(provider_key)


def load_provider_runtime_policy() -> ProviderRuntimePolicy:
    external_provider_enabled = _read_bool("VERIFIER_EXTERNAL_PROVIDER_ENABLED", default=False)
    default_timeout_ms = _read_int("VERIFIER_PROVIDER_DEFAULT_TIMEOUT_MS", 3000)
    default_retry_budget = _read_int("VERIFIER_PROVIDER_DEFAULT_RETRY_BUDGET", 0)
    request_size_limit_bytes = _read_int("VERIFIER_PROVIDER_REQUEST_SIZE_LIMIT_BYTES", 32_768)
    response_size_limit_bytes = _read_int("VERIFIER_PROVIDER_RESPONSE_SIZE_LIMIT_BYTES", 65_536)
    global_domain_allowlist = tuple(_read_csv("VERIFIER_PROVIDER_DOMAIN_ALLOWLIST"))
    transition_config = _build_transition_config(external_provider_enabled=external_provider_enabled)
    enabled_provider_keys = tuple(
        value
        for value in _read_csv(
            "VERIFIER_ENABLED_PROVIDERS",
            default=_default_enabled_provider_keys(transition_config.provider_operating_mode),
        )
        if value
    )

    provider_configs = {
        "entra_verified_id": _build_provider_config(
            provider_key="entra_verified_id",
            provider_label="Microsoft Entra Verified ID",
            default_timeout_ms=default_timeout_ms,
            default_retry_budget=default_retry_budget,
            global_domain_allowlist=global_domain_allowlist,
            transition_config=transition_config,
        ),
        "identity_http": _build_provider_config(
            provider_key="identity_http",
            provider_label="Supplementary Identity HTTP Provider",
            default_timeout_ms=default_timeout_ms,
            default_retry_budget=default_retry_budget,
            global_domain_allowlist=global_domain_allowlist,
            transition_config=transition_config,
        ),
        "academic_registry_http": _build_provider_config(
            provider_key="academic_registry_http",
            provider_label="Supplementary Academic Registry HTTP Provider",
            default_timeout_ms=default_timeout_ms,
            default_retry_budget=default_retry_budget,
            global_domain_allowlist=global_domain_allowlist,
            transition_config=transition_config,
        ),
    }

    return ProviderRuntimePolicy(
        external_provider_enabled=external_provider_enabled,
        enabled_provider_keys=enabled_provider_keys or tuple(
            _default_enabled_provider_keys(transition_config.provider_operating_mode)
        ),
        default_timeout_ms=default_timeout_ms,
        default_retry_budget=default_retry_budget,
        request_size_limit_bytes=request_size_limit_bytes,
        response_size_limit_bytes=response_size_limit_bytes,
        global_domain_allowlist=global_domain_allowlist,
        provider_configs=provider_configs,
        transition_config=transition_config,
    )


def minimize_payload(
    payload: dict[str, Any] | None,
    *,
    allow_document_upload: bool,
    max_string_chars: int = 160,
) -> tuple[dict[str, Any], bool]:
    redaction_applied = False

    def _walk(value: Any, key_hint: str = "") -> Any:
        nonlocal redaction_applied
        lowered = key_hint.lower()
        if lowered in SENSITIVE_KEYS and not allow_document_upload:
            redaction_applied = True
            return "[redacted]"

        if isinstance(value, dict):
            output = {}
            for key, nested in value.items():
                result = _walk(nested, str(key))
                if result == "[omitted]":
                    continue
                output[str(key)] = result
            return output

        if isinstance(value, list):
            return [_walk(item, key_hint) for item in value[:10]]

        if isinstance(value, (bytes, bytearray)):
            redaction_applied = True
            return "[redacted-bytes]"

        if isinstance(value, str):
            normalized = value.strip()
            if not allow_document_upload and len(normalized) > max_string_chars:
                redaction_applied = True
                return f"{normalized[:max_string_chars]}...[truncated]"
            return normalized

        return value

    minimized = _walk(dict(payload or {}))
    return minimized, redaction_applied


def normalize_domain_allowlist(*values: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if not candidate:
            continue
        if "://" in candidate:
            parsed = urlparse(candidate)
            host = parsed.hostname
        else:
            host = candidate
        if host:
            normalized.append(host.lower())
    return tuple(dict.fromkeys(normalized))


def _build_provider_config(
    *,
    provider_key: str,
    provider_label: str,
    default_timeout_ms: int,
    default_retry_budget: int,
    global_domain_allowlist: tuple[str, ...],
    transition_config: ProviderTransitionConfig,
) -> ProviderConfig:
    env_prefix = f"VERIFIER_PROVIDER_{provider_key.upper()}"
    base_url = os.getenv(f"{env_prefix}_BASE_URL")
    explicit_domain_allowlist = normalize_domain_allowlist(
        *(_read_csv(f"{env_prefix}_DOMAIN_ALLOWLIST") or [])
    )
    if explicit_domain_allowlist:
        domain_allowlist = explicit_domain_allowlist
    elif base_url:
        domain_allowlist = normalize_domain_allowlist(base_url, *global_domain_allowlist)
    else:
        domain_allowlist = global_domain_allowlist

    return ProviderConfig(
        provider_key=provider_key,
        provider_label=provider_label,
        enabled=_read_bool(f"{env_prefix}_ENABLED", default=False),
        base_url=base_url,
        timeout_ms=_read_int(f"{env_prefix}_TIMEOUT_MS", default_timeout_ms),
        retry_budget=_read_int(f"{env_prefix}_RETRY_BUDGET", default_retry_budget),
        outbound_mode=os.getenv(f"{env_prefix}_OUTBOUND_MODE", OUTBOUND_MODE_HTTP_JSON),
        allow_document_upload=_read_bool(f"{env_prefix}_ALLOW_DOCUMENT_UPLOAD", default=False),
        field_lookup_preferred=_read_bool(f"{env_prefix}_FIELD_LOOKUP_REQUIRED", default=True),
        require_minimization=_read_bool(f"{env_prefix}_REQUIRE_MINIMIZATION", default=True),
        domain_allowlist=domain_allowlist,
        api_key=os.getenv(f"{env_prefix}_API_KEY"),
        demo_enabled=_read_bool(f"{env_prefix}_DEMO_ENABLED", default=True),
        operating_mode=transition_config.provider_operating_mode,
        execution_environment_label=transition_config.execution_environment_label,
    )


def build_local_mock_config(transition_config: ProviderTransitionConfig | None = None) -> ProviderConfig:
    resolved_transition = transition_config or ProviderTransitionConfig(
        provider_operating_mode=PROVIDER_OPERATING_MODE_LOCAL_MOCK,
        enabled_provider_modes=[PROVIDER_OPERATING_MODE_LOCAL_MOCK],
        execution_environment_label="Local mock environment",
    )
    return ProviderConfig(
        provider_key="local_mock",
        provider_label="Local Mock Provider",
        enabled=True,
        base_url=None,
        timeout_ms=50,
        retry_budget=0,
        outbound_mode=OUTBOUND_MODE_LOCAL_ONLY,
        allow_document_upload=False,
        field_lookup_preferred=True,
        require_minimization=True,
        domain_allowlist=(),
        api_key=None,
        demo_enabled=True,
        operating_mode=resolved_transition.provider_operating_mode,
        execution_environment_label=resolved_transition.execution_environment_label,
    )


def _build_transition_config(*, external_provider_enabled: bool) -> ProviderTransitionConfig:
    requested_mode = os.getenv("VERIFIER_PROVIDER_OPERATING_MODE") or os.getenv("PROVIDER_OPERATING_MODE")
    live_provider_enabled = _read_bool(
        "VERIFIER_LIVE_PROVIDER_ENABLED",
        default=external_provider_enabled,
    )
    operating_mode = _resolve_provider_operating_mode(
        requested_mode=requested_mode,
        live_provider_enabled=live_provider_enabled,
    )
    enabled_provider_modes = _read_csv(
        "VERIFIER_ENABLED_PROVIDER_MODES",
        default=[operating_mode],
    )
    execution_environment_label = (
        os.getenv("VERIFIER_EXECUTION_ENVIRONMENT_LABEL")
        or os.getenv("EXECUTION_ENVIRONMENT_LABEL")
        or _default_environment_label(operating_mode)
    )
    demo_profile_key = os.getenv("VERIFIER_DEMO_PROFILE_KEY") or os.getenv("DEMO_PROFILE_KEY") or None

    notes = [
        _default_transition_note(operating_mode),
    ]
    explicit_transition_note = os.getenv("VERIFIER_PROVIDER_TRANSITION_NOTES") or os.getenv("PROVIDER_TRANSITION_NOTES")
    if explicit_transition_note:
        notes.append(explicit_transition_note.strip())
    if operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK and demo_profile_key:
        notes.append(f"Seeded demo profile '{demo_profile_key}' will be used when the session does not persist an override.")

    return ProviderTransitionConfig(
        preferred_provider_rail=os.getenv("VERIFIER_PREFERRED_PROVIDER_RAIL", "entra_verified_id").strip() or "entra_verified_id",
        provider_operating_mode=operating_mode,
        enabled_provider_modes=[mode for mode in enabled_provider_modes if mode],
        demo_profile_key=demo_profile_key,
        live_provider_enabled=live_provider_enabled and operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
        fallback_policy=os.getenv("VERIFIER_FALLBACK_POLICY", "SUPPLEMENTARY_THEN_LOCAL_MOCK"),
        manual_review_policy=os.getenv("VERIFIER_MANUAL_REVIEW_POLICY", "RECOMMEND_ON_UNCERTAINTY"),
        execution_environment_label=execution_environment_label,
        provider_transition_notes=[note for note in notes if note],
    )


def _resolve_provider_operating_mode(*, requested_mode: str | None, live_provider_enabled: bool) -> str:
    allowed = {
        PROVIDER_OPERATING_MODE_DEMO_MOCK,
        PROVIDER_OPERATING_MODE_LOCAL_MOCK,
        PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
        PROVIDER_OPERATING_MODE_LIVE_DISABLED,
        PROVIDER_OPERATING_MODE_MANUAL_ONLY,
    }
    normalized_requested_mode = str(requested_mode or "").strip().upper()
    if live_provider_enabled and normalized_requested_mode in {
        "",
        PROVIDER_OPERATING_MODE_LOCAL_MOCK,
        PROVIDER_OPERATING_MODE_LIVE_DISABLED,
        PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
    }:
        return PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED
    if normalized_requested_mode in allowed:
        return normalized_requested_mode
    if live_provider_enabled:
        return PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED
    return PROVIDER_OPERATING_MODE_LIVE_DISABLED


def _default_enabled_provider_keys(operating_mode: str) -> list[str]:
    if operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
        return ["entra_verified_id", "identity_http", "academic_registry_http", "local_mock"]
    if operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        return ["entra_verified_id", "identity_http", "academic_registry_http", "local_mock"]
    if operating_mode == PROVIDER_OPERATING_MODE_MANUAL_ONLY:
        return []
    return ["local_mock"]


def _default_environment_label(operating_mode: str) -> str:
    if operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
        return "POC demo environment"
    if operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        return "External provider environment"
    if operating_mode == PROVIDER_OPERATING_MODE_MANUAL_ONLY:
        return "Manual review environment"
    if operating_mode == PROVIDER_OPERATING_MODE_LOCAL_MOCK:
        return "Local mock environment"
    return "Live-disabled environment"


def _default_transition_note(operating_mode: str) -> str:
    if operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
        return "Demo-mock mode is active. Provider results are seeded and normalized locally for presentation."
    if operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        return "External provider execution is configured. Live outbound calls remain bounded by the provider policy layer."
    if operating_mode == PROVIDER_OPERATING_MODE_LOCAL_MOCK:
        return "Local mock mode is active. No external provider calls will be attempted."
    if operating_mode == PROVIDER_OPERATING_MODE_MANUAL_ONLY:
        return "Manual-only mode is active. Credentials without existing evidence should route to manual review."
    return "Live provider execution is disabled. Supplementary mock or manual fallback paths remain available."


def _read_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return max(int(value), 0)
    except ValueError:
        return default


def _read_csv(name: str, default: list[str] | None = None) -> list[str]:
    value = os.getenv(name)
    if value in (None, ""):
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]
