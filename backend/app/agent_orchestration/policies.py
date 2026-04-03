from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..inference import load_nvidia_inference_config


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


def _read_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AgentRuntimePolicy:
    orchestration_enabled: bool = True
    provider_key: str = "deterministic"
    external_provider_enabled: bool = False
    timeout_ms: int = 2500
    route_override_confidence: float = 0.74
    classification_override_confidence: float = 0.74
    max_fields_for_provider: int = 18
    max_value_chars: int = 160
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_reasoning_model: str = "minimaxai/minimax-m2.5"
    nvidia_pii_model: str = "nvidia/gliner-pii"
    nvidia_api_key: str | None = None
    nvidia_retry_budget: int = 0
    nvidia_max_input_chars: int = 4000
    nvidia_reasoning_enabled: bool = True
    nvidia_gliner_enabled: bool = True


def load_agent_runtime_policy() -> AgentRuntimePolicy:
    nvidia = load_nvidia_inference_config()
    return AgentRuntimePolicy(
        orchestration_enabled=_read_bool("AGENT_ORCHESTRATION_ENABLED", True),
        provider_key=os.getenv("AGENT_PROVIDER", "deterministic").strip().lower() or "deterministic",
        external_provider_enabled=_read_bool("AGENT_EXTERNAL_PROVIDER_ENABLED", False),
        timeout_ms=_read_int("AGENT_TIMEOUT_MS", 2500),
        route_override_confidence=_read_float("AGENT_ROUTE_OVERRIDE_CONFIDENCE", 0.74),
        classification_override_confidence=_read_float("AGENT_CLASSIFICATION_OVERRIDE_CONFIDENCE", 0.74),
        max_fields_for_provider=_read_int("AGENT_MAX_FIELDS_FOR_PROVIDER", 18),
        max_value_chars=_read_int("AGENT_MAX_VALUE_CHARS", 160),
        nvidia_base_url=nvidia.base_url,
        nvidia_reasoning_model=nvidia.reasoning_model,
        nvidia_pii_model=nvidia.pii_model,
        nvidia_api_key=nvidia.api_key,
        nvidia_retry_budget=nvidia.retry_budget,
        nvidia_max_input_chars=nvidia.max_input_chars,
        nvidia_reasoning_enabled=nvidia.reasoning_enabled,
        nvidia_gliner_enabled=nvidia.pii_enrichment_enabled,
    )


def minimize_extraction_payload(
    extraction_payload: dict[str, Any] | None,
    *,
    max_fields: int,
    max_value_chars: int,
) -> dict[str, Any] | None:
    if not extraction_payload:
        return None

    fields = []
    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    generalized_credentials = generalized_analysis.get("generalized_credentials_payload") or []
    if isinstance(generalized_credentials, list):
        for index, credential in enumerate(generalized_credentials):
            if index >= max_fields or not isinstance(credential, dict):
                break
            value = credential.get("value")
            fields.append(
                {
                    "key": str(credential.get("credential_id") or ""),
                    "label": str(credential.get("label") or ""),
                    "value": _truncate_text(value, max_value_chars),
                    "confidence": credential.get("confidence"),
                    "page": credential.get("page"),
                    "category": credential.get("category"),
                }
            )

    if not fields:
        for index, candidate in enumerate(list(extraction_payload.get("field_candidates") or [])[:max_fields]):
            if not isinstance(candidate, dict):
                continue
            value = candidate.get("raw_value")
            fields.append(
                {
                    "key": str(candidate.get("candidate_id") or ""),
                    "label": str(candidate.get("label") or ""),
                    "value": _truncate_text(value, max_value_chars),
                    "confidence": candidate.get("confidence"),
                    "page": candidate.get("page"),
                    "category": candidate.get("category"),
                }
            )

    return {
        "document_type": str(extraction_payload.get("document_type") or "unknown"),
        "page_count": extraction_payload.get("page_count"),
        "used_ocr": bool(extraction_payload.get("used_ocr") or extraction_payload.get("ocr_used")),
        "fields": fields,
        "warnings": [
            warning.get("code") if isinstance(warning, dict) else str(warning)
            for warning in list(extraction_payload.get("warnings") or [])[:8]
        ],
        "enrichment_metadata": extraction_payload.get("enrichment_metadata") or {},
    }


def _truncate_text(value: Any, max_value_chars: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) <= max_value_chars:
        return text
    return f"{text[:max_value_chars].rstrip()}..."

