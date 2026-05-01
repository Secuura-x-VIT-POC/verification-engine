from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


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
    provider_key: str = "gemini"
    external_provider_enabled: bool = False
    timeout_ms: int = 2500
    route_override_confidence: float = 0.74
    classification_override_confidence: float = 0.74
    max_fields_for_provider: int = 18
    max_value_chars: int = 160
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.0
    gemini_demo_raw_text_enabled: bool = True
    gemini_structured_output_enabled: bool = True
    gemini_max_input_chars: int = 12000


def load_agent_runtime_policy() -> AgentRuntimePolicy:
    return AgentRuntimePolicy(
        orchestration_enabled=_read_bool("AGENT_ORCHESTRATION_ENABLED", True),
        provider_key=os.getenv("AGENT_PROVIDER", "gemini").strip().lower() or "gemini",
        external_provider_enabled=_read_bool("AGENT_EXTERNAL_PROVIDER_ENABLED", False),
        timeout_ms=_read_int("AGENT_TIMEOUT_MS", 2500),
        route_override_confidence=_read_float("AGENT_ROUTE_OVERRIDE_CONFIDENCE", 0.74),
        classification_override_confidence=_read_float("AGENT_CLASSIFICATION_OVERRIDE_CONFIDENCE", 0.74),
        max_fields_for_provider=_read_int("AGENT_MAX_FIELDS_FOR_PROVIDER", 18),
        max_value_chars=_read_int("AGENT_MAX_VALUE_CHARS", 160),
        gemini_api_key=(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip() or None,
        gemini_model=(os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        gemini_temperature=_read_float("GEMINI_TEMPERATURE", 0.0),
        gemini_demo_raw_text_enabled=_read_bool("GEMINI_DEMO_RAW_TEXT_ENABLED", True),
        gemini_structured_output_enabled=_read_bool("GEMINI_STRUCTURED_OUTPUT_ENABLED", True),
        gemini_max_input_chars=_read_int("GEMINI_MAX_INPUT_CHARS", 12000),
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
    view_payload = extraction_payload.get("view") if isinstance(extraction_payload.get("view"), dict) else extraction_payload
    generalized_analysis = view_payload.get("generalized_analysis") or {}
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
        for index, candidate in enumerate(list(view_payload.get("field_candidates") or [])[:max_fields]):
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
        "document_type": str(view_payload.get("document_type") or extraction_payload.get("document_type") or "unknown"),
        "page_count": view_payload.get("page_count") or extraction_payload.get("page_count"),
        "used_ocr": bool(view_payload.get("used_ocr") or extraction_payload.get("used_ocr") or extraction_payload.get("ocr_used")),
        "fields": fields,
        "warnings": [
            warning.get("code") if isinstance(warning, dict) else str(warning)
            for warning in list(view_payload.get("warnings") or extraction_payload.get("warnings") or [])[:8]
        ],
    }


def _truncate_text(value: Any, max_value_chars: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) <= max_value_chars:
        return text
    return f"{text[:max_value_chars].rstrip()}..."

