from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..verifier_providers.http_client import SafeHttpClientError, SafeHttpJsonClient


DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_REASONING_MODEL = "minimaxai/minimax-m2.5"
DEFAULT_NVIDIA_PII_MODEL = "nvidia/gliner-pii"


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class NvidiaInferenceConfig:
    api_key: str | None = None
    base_url: str = DEFAULT_NVIDIA_BASE_URL
    reasoning_model: str = DEFAULT_NVIDIA_REASONING_MODEL
    pii_model: str = DEFAULT_NVIDIA_PII_MODEL
    timeout_ms: int = 4000
    retry_budget: int = 0
    max_input_chars: int = 4000
    request_size_limit_bytes: int = 65536
    response_size_limit_bytes: int = 65536
    reasoning_enabled: bool = True
    pii_enrichment_enabled: bool = True


class NvidiaInferenceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_nvidia_inference_config() -> NvidiaInferenceConfig:
    reasoning_toggle = os.getenv("NVIDIA_REASONING_ENABLED")
    if reasoning_toggle is None:
        reasoning_toggle = os.getenv("AGENT_ENABLE_REASONING")

    pii_toggle = os.getenv("NVIDIA_GLINER_PREPROCESSING_ENABLED")
    if pii_toggle is None:
        pii_toggle = os.getenv("AGENT_ENABLE_PII_ENRICHMENT")

    timeout_override = os.getenv("NVIDIA_TIMEOUT_MS")
    if timeout_override is None:
        timeout_override = os.getenv("AGENT_REQUEST_TIMEOUT_MS")

    return NvidiaInferenceConfig(
        api_key=(
            (os.getenv("NVIDIA_API_KEY") or "").strip()
            or (os.getenv("AGENT_NVIDIA_API_KEY") or "").strip()
            or None
        ),
        base_url=(
            (os.getenv("NVIDIA_BASE_URL") or "").strip()
            or (os.getenv("AGENT_NVIDIA_BASE_URL") or "").strip()
            or DEFAULT_NVIDIA_BASE_URL
        ),
        reasoning_model=(
            (os.getenv("NVIDIA_REASONING_MODEL") or "").strip()
            or (os.getenv("AGENT_NVIDIA_MODEL") or "").strip()
            or DEFAULT_NVIDIA_REASONING_MODEL
        ),
        pii_model=(
            (os.getenv("NVIDIA_PII_MODEL") or "").strip()
            or DEFAULT_NVIDIA_PII_MODEL
        ),
        timeout_ms=_read_int_from_value(timeout_override, 4000),
        retry_budget=_read_int("NVIDIA_RETRY_BUDGET", 0),
        max_input_chars=_read_int("NVIDIA_MAX_TEXT_LENGTH", 4000),
        request_size_limit_bytes=_read_int("NVIDIA_REQUEST_SIZE_LIMIT_BYTES", 65536),
        response_size_limit_bytes=_read_int("NVIDIA_RESPONSE_SIZE_LIMIT_BYTES", 65536),
        reasoning_enabled=_read_bool_from_value(reasoning_toggle, True),
        pii_enrichment_enabled=_read_bool_from_value(pii_toggle, True),
    )


def _read_bool_from_value(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_from_value(raw_value: str | None, default: int) -> int:
    if raw_value in (None, ""):
        return default
    try:
        return max(int(raw_value), 0)
    except ValueError:
        return default


class NvidiaChatClient:
    def __init__(self, config: NvidiaInferenceConfig | None = None):
        self.config = config or load_nvidia_inference_config()
        self.http_client = SafeHttpJsonClient(
            request_size_limit_bytes=self.config.request_size_limit_bytes,
            response_size_limit_bytes=self.config.response_size_limit_bytes,
        )

    def is_configured(self) -> tuple[bool, str | None]:
        if not self.config.api_key:
            return False, "NVIDIA API key is not configured."
        if not self.config.base_url:
            return False, "NVIDIA base URL is not configured."
        return True, None

    def chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        timeout_ms: int | None = None,
        retry_budget: int | None = None,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        available, reason = self.is_configured()
        if not available:
            raise NvidiaInferenceError("not_configured", reason or "NVIDIA inference is not configured.")

        url = self._build_chat_completions_url()
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt.strip()},
                {
                    "role": "user",
                    "content": _truncate_text(
                        json.dumps(user_payload, ensure_ascii=True, default=str),
                        self.config.max_input_chars,
                    ),
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.http_client.post_json(
                url=url,
                payload=payload,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout_ms=timeout_ms or self.config.timeout_ms,
                retry_budget=self.config.retry_budget if retry_budget is None else retry_budget,
                domain_allowlist=(self._resolved_host(),),
            )
        except SafeHttpClientError as exc:
            raise NvidiaInferenceError(exc.code, str(exc)) from exc

        content = _extract_content_text(response.payload)
        parsed = _parse_json_content(content)
        if not isinstance(parsed, dict):
            raise NvidiaInferenceError("invalid_response", "NVIDIA inference did not return a JSON object.")
        return parsed

    def _build_chat_completions_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    def _resolved_host(self) -> str:
        return (urlparse(self.config.base_url).hostname or "").lower()


def _truncate_text(value: str, max_length: int) -> str:
    if max_length <= 0 or len(value) <= max_length:
        return value
    return f"{value[:max_length].rstrip()}..."


def _extract_content_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise NvidiaInferenceError("invalid_response", "NVIDIA response did not include choices.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise NvidiaInferenceError("invalid_response", "NVIDIA response did not include a message payload.")
    content = message.get("content")
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=True)
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
            elif isinstance(item, str):
                chunks.append(item)
        return "".join(chunks).strip()
    if isinstance(content, str):
        return content.strip()
    raise NvidiaInferenceError("invalid_response", "NVIDIA response content was empty.")


def _parse_json_content(content: str) -> Any:
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.strip("`")
        if "\n" in normalized:
            normalized = normalized.split("\n", 1)[1]
        if normalized.endswith("```"):
            normalized = normalized[:-3]
        normalized = normalized.strip()
    try:
        return json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise NvidiaInferenceError("invalid_json", "NVIDIA response did not contain valid JSON.") from exc
