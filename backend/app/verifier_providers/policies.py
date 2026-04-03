from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .contracts import OUTBOUND_MODE_HTTP_JSON, OUTBOUND_MODE_LOCAL_ONLY


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

    def is_provider_enabled(self, provider_key: str) -> bool:
        config = self.provider_configs.get(provider_key)
        if config is None:
            return provider_key == "local_mock"
        if provider_key == "local_mock":
            return True
        return self.external_provider_enabled and config.enabled and provider_key in self.enabled_provider_keys

    def config_for(self, provider_key: str) -> ProviderConfig | None:
        return self.provider_configs.get(provider_key)


def load_provider_runtime_policy() -> ProviderRuntimePolicy:
    external_provider_enabled = _read_bool("VERIFIER_EXTERNAL_PROVIDER_ENABLED", default=False)
    enabled_provider_keys = tuple(
        value
        for value in _read_csv("VERIFIER_ENABLED_PROVIDERS", default=["local_mock"])
        if value
    )
    default_timeout_ms = _read_int("VERIFIER_PROVIDER_DEFAULT_TIMEOUT_MS", 3000)
    default_retry_budget = _read_int("VERIFIER_PROVIDER_DEFAULT_RETRY_BUDGET", 0)
    request_size_limit_bytes = _read_int("VERIFIER_PROVIDER_REQUEST_SIZE_LIMIT_BYTES", 32_768)
    response_size_limit_bytes = _read_int("VERIFIER_PROVIDER_RESPONSE_SIZE_LIMIT_BYTES", 65_536)
    global_domain_allowlist = tuple(_read_csv("VERIFIER_PROVIDER_DOMAIN_ALLOWLIST"))

    provider_configs = {
        "identity_http": _build_provider_config(
            provider_key="identity_http",
            provider_label="Identity HTTP Provider",
            default_timeout_ms=default_timeout_ms,
            default_retry_budget=default_retry_budget,
            global_domain_allowlist=global_domain_allowlist,
        ),
        "academic_registry_http": _build_provider_config(
            provider_key="academic_registry_http",
            provider_label="Academic Registry HTTP Provider",
            default_timeout_ms=default_timeout_ms,
            default_retry_budget=default_retry_budget,
            global_domain_allowlist=global_domain_allowlist,
        ),
    }

    return ProviderRuntimePolicy(
        external_provider_enabled=external_provider_enabled,
        enabled_provider_keys=enabled_provider_keys or ("local_mock",),
        default_timeout_ms=default_timeout_ms,
        default_retry_budget=default_retry_budget,
        request_size_limit_bytes=request_size_limit_bytes,
        response_size_limit_bytes=response_size_limit_bytes,
        global_domain_allowlist=global_domain_allowlist,
        provider_configs=provider_configs,
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
    )


def build_local_mock_config() -> ProviderConfig:
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
    )


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
