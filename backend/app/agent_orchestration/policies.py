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
    provider_key: str = "deterministic"
    external_provider_enabled: bool = False
    timeout_ms: int = 2500
    route_override_confidence: float = 0.74
    classification_override_confidence: float = 0.74
    max_fields_for_provider: int = 18
    max_value_chars: int = 160
    nvidia_base_url: str | None = None
    nvidia_model: str | None = None
    nvidia_api_key: str | None = None


def load_agent_runtime_policy() -> AgentRuntimePolicy:
    return AgentRuntimePolicy(
        orchestration_enabled=_read_bool("AGENT_ORCHESTRATION_ENABLED", True),
        provider_key=os.getenv("AGENT_PROVIDER", "deterministic").strip().lower() or "deterministic",
        external_provider_enabled=_read_bool("AGENT_EXTERNAL_PROVIDER_ENABLED", False),
        timeout_ms=_read_int("AGENT_TIMEOUT_MS", 2500),
        route_override_confidence=_read_float("AGENT_ROUTE_OVERRIDE_CONFIDENCE", 0.74),
        classification_override_confidence=_read_float("AGENT_CLASSIFICATION_OVERRIDE_CONFIDENCE", 0.74),
        max_fields_for_provider=_read_int("AGENT_MAX_FIELDS_FOR_PROVIDER", 18),
        max_value_chars=_read_int("AGENT_MAX_VALUE_CHARS", 160),
        nvidia_base_url=(os.getenv("AGENT_NVIDIA_BASE_URL") or "").strip() or None,
        nvidia_model=(os.getenv("AGENT_NVIDIA_MODEL") or "").strip() or None,
        nvidia_api_key=(os.getenv("AGENT_NVIDIA_API_KEY") or "").strip() or None,
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
    for detail in list(extraction_payload.get("field_details") or [])[:max_fields]:
        if not isinstance(detail, dict):
            continue
        value = detail.get("value")
        fields.append(
            {
                "key": str(detail.get("key") or ""),
                "label": str(detail.get("label") or ""),
                "value": _truncate_text(value, max_value_chars),
                "confidence": detail.get("confidence"),
                "page": _resolve_page(detail),
            }
        )

    if not fields:
        raw_fields = extraction_payload.get("fields") or {}
        for index, (key, value) in enumerate(raw_fields.items()):
            if index >= max_fields:
                break
            resolved = value.get("value") if isinstance(value, dict) else value
            fields.append(
                {
                    "key": str(key),
                    "label": str(key).replace("_", " ").title(),
                    "value": _truncate_text(resolved, max_value_chars),
                    "confidence": value.get("confidence") if isinstance(value, dict) else None,
                    "page": None,
                }
            )

    return {
        "document_type": str(extraction_payload.get("document_type") or "unknown"),
        "page_count": extraction_payload.get("page_count"),
        "used_ocr": bool(extraction_payload.get("used_ocr") or extraction_payload.get("ocr_used")),
        "fields": fields,
    }


def _truncate_text(value: Any, max_value_chars: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) <= max_value_chars:
        return text
    return f"{text[:max_value_chars].rstrip()}..."


def _resolve_page(detail: dict[str, Any]) -> int | None:
    boxes = detail.get("bounding_boxes") or []
    if isinstance(boxes, list) and boxes:
        first_box = boxes[0]
        if isinstance(first_box, dict):
            try:
                return int(first_box.get("page"))
            except (TypeError, ValueError):
                return None
    return None
