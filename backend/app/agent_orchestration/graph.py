from __future__ import annotations

import copy
import json
import logging
import re
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from .state import GeminiNormalizationState


LOGGER = logging.getLogger(__name__)

_CANONICAL_FIELDS = ("name", "institution", "credential", "date", "id")
_MANDATORY_FIELDS = {"name", "institution", "credential", "id"}
_ALLOWED_DOCUMENT_TYPES = {
    "academic_credential",
    "report_card",
    "identity_document",
    "certificate_document",
    "financial_document",
    "unknown",
}


def build_gemini_normalization_graph(
    *,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
):
    graph = StateGraph(GeminiNormalizationState)
    graph.add_node(
        "gemini_normalization",
        lambda state: _run_gemini_normalization(state, model=model, temperature=temperature),
    )
    graph.add_node("validate_normalization", _validate_normalization)
    graph.add_edge(START, "gemini_normalization")
    graph.add_edge("gemini_normalization", "validate_normalization")
    graph.add_edge("validate_normalization", END)
    return graph.compile()


def _run_gemini_normalization(
    state: GeminiNormalizationState,
    *,
    model: str,
    temperature: float,
) -> dict[str, Any]:
    raw_extraction = state.get("raw_extraction") or {}
    if not isinstance(raw_extraction, dict):
        return _fallback_state({}, ["raw extraction payload is not a dict"])

    try:
        llm = _build_gemini_llm(model=model, temperature=temperature)
        LOGGER.info("LLM_NORMALIZATION_STARTED provider=gemini model=%s", model)
        response = llm.invoke(_build_normalization_prompt(raw_extraction))
        parsed_output = _parse_json_response(getattr(response, "content", response))
        LOGGER.info("LLM_NORMALIZATION_COMPLETED provider=gemini model=%s", model)
        return {
            "gemini_output": parsed_output,
            "fallback_used": False,
            "validation_errors": [],
        }
    except Exception as exc:
        LOGGER.warning("LLM_NORMALIZATION_FALLBACK reason=invoke_or_parse_failed error=%s", exc)
        return _fallback_state(raw_extraction, [str(exc)])


def _validate_normalization(state: GeminiNormalizationState) -> dict[str, Any]:
    raw_extraction = state.get("raw_extraction") or {}
    if state.get("fallback_used"):
        return {
            "normalized_extraction": copy.deepcopy(raw_extraction),
            "fallback_used": True,
            "validation_errors": list(state.get("validation_errors") or []),
        }

    errors: list[str] = []
    gemini_output = state.get("gemini_output")
    if not isinstance(gemini_output, dict):
        errors.append("Gemini output is not a JSON object")
        return _fallback_state(raw_extraction, errors)

    errors.extend(_validate_gemini_output(gemini_output))

    if errors:
        LOGGER.warning(
            "LLM_NORMALIZATION_VALIDATION_FAILED error_count=%s errors=%s",
            len(errors),
            errors,
        )
        return _fallback_state(raw_extraction, errors)

    try:
        normalized = _merge_normalized_output(raw_extraction, gemini_output)
        return {
            "normalized_extraction": normalized,
            "fallback_used": False,
            "validation_errors": [],
        }
    except Exception as exc:
        LOGGER.warning("LLM_NORMALIZATION_VALIDATION_FAILED error_count=1 errors=%s", [str(exc)])
        return _fallback_state(raw_extraction, [str(exc)])


def _build_gemini_llm(*, model: str, temperature: float):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, temperature=temperature)


def _build_normalization_prompt(raw_extraction: dict[str, Any]) -> str:
    return (
        "You are an in-memory document normalization layer inside a deterministic "
        "verification system. Classify the document, refine extracted fields, "
        "normalize values, and resolve ambiguities only. Do not decide trust, "
        "do not recommend verification outcome, do not choose connectors, and "
        "do not include prose.\n\n"
        "Return JSON only with this shape:\n"
        "{\n"
        '  "document_type": "academic_credential|report_card|identity_document|certificate_document|financial_document|unknown",\n'
        '  "fields": {"name": "", "institution": "", "credential": "", "date": "", "id": ""},\n'
        '  "confidence": {"name": 0.0, "institution": 0.0, "credential": 0.0, "date": 0.0, "id": 0.0},\n'
        '  "connector_input": {"name": "", "degree": "", "institution": "", "document_id": ""},\n'
        '  "ambiguities": []\n'
        "}\n\n"
        f"Raw extraction payload:\n{json.dumps(raw_extraction, default=str)}"
    )


def _parse_json_response(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text") if isinstance(part, dict) else part) for part in content
        )
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    return json.loads(text)


def _merge_normalized_output(
    raw_extraction: dict[str, Any],
    gemini_output: dict[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(raw_extraction)
    field_values = {
        name: str((gemini_output.get("fields") or {}).get(name) or "").strip()
        for name in _CANONICAL_FIELDS
    }
    confidence_values = {
        name: _coerce_confidence((gemini_output.get("confidence") or {}).get(name))
        for name in _CANONICAL_FIELDS
    }
    document_type = str(gemini_output.get("document_type") or "").strip() or "unknown"

    view = dict(normalized.get("view") or {})
    view_fields = dict(view.get("fields") or {})
    view_confidence = dict(view.get("confidence") or {})
    for name, value in field_values.items():
        if value:
            view_fields[name] = value
            view_confidence[name] = confidence_values[name]
    view["fields"] = view_fields
    view["confidence"] = view_confidence
    view["document_type"] = document_type
    normalized["view"] = view
    normalized["document_type"] = document_type

    normalized["trust_input"] = {
        "document_type": document_type,
        "fields": _merge_trust_fields(normalized.get("trust_input"), field_values, confidence_values),
    }

    existing_connector_input = dict(normalized.get("connector_input") or {})
    gemini_connector_input = dict(gemini_output.get("connector_input") or {})
    connector_input = {
        "name": _first_nonempty(gemini_connector_input.get("name"), field_values["name"], existing_connector_input.get("name")),
        "degree": _first_nonempty(gemini_connector_input.get("degree"), field_values["credential"], existing_connector_input.get("degree")),
        "institution": _first_nonempty(
            gemini_connector_input.get("institution"),
            field_values["institution"],
            existing_connector_input.get("institution"),
        ),
        "document_id": _first_nonempty(gemini_connector_input.get("document_id"), field_values["id"], existing_connector_input.get("document_id")),
    }
    normalized["connector_input"] = connector_input
    return normalized


def _validate_gemini_output(gemini_output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    document_type = gemini_output.get("document_type")
    fields = gemini_output.get("fields")
    confidence = gemini_output.get("confidence")
    connector_input = gemini_output.get("connector_input")
    ambiguities = gemini_output.get("ambiguities")

    if not isinstance(document_type, str) or not document_type.strip():
        errors.append("document_type must be a non-empty string")
    elif document_type.strip() not in _ALLOWED_DOCUMENT_TYPES:
        errors.append("document_type is not allowed")

    if not isinstance(fields, dict):
        errors.append("fields must be an object")
        fields = {}
    if not isinstance(confidence, dict):
        errors.append("confidence must be an object")
        confidence = {}
    if not isinstance(connector_input, dict):
        errors.append("connector_input must be an object")
        connector_input = {}
    if ambiguities is not None and not isinstance(ambiguities, list):
        errors.append("ambiguities must be a list when present")

    for name in _CANONICAL_FIELDS:
        value = fields.get(name)
        if value is not None and not isinstance(value, str):
            errors.append(f"fields.{name} must be a string")
        if name in _MANDATORY_FIELDS and not str(value or "").strip():
            errors.append(f"fields.{name} is required")

        confidence_value = confidence.get(name)
        if not isinstance(confidence_value, (int, float)):
            errors.append(f"confidence.{name} must be numeric")
        elif confidence_value < 0 or confidence_value > 1:
            errors.append(f"confidence.{name} must be between 0 and 1")

    for name in ("name", "degree", "institution", "document_id"):
        value = connector_input.get(name)
        if value is not None and not isinstance(value, str):
            errors.append(f"connector_input.{name} must be a string")

    date_value = str(fields.get("date") or "").strip()
    if date_value:
        match = re.search(r"(19\d{2}|20\d{2})", date_value)
        if not match:
            errors.append("fields.date must contain a four-digit year when present")
        else:
            year = int(match.group(1))
            max_year = datetime.utcnow().year + 1
            if year < 1900 or year > max_year:
                errors.append("fields.date year is out of range")

    return errors


def _merge_trust_fields(
    existing_trust_input: Any,
    field_values: dict[str, str],
    confidence_values: dict[str, float],
) -> list[dict[str, Any]]:
    existing_fields = []
    if isinstance(existing_trust_input, dict) and isinstance(existing_trust_input.get("fields"), list):
        existing_fields = [dict(field) for field in existing_trust_input["fields"] if isinstance(field, dict)]

    by_name = {str(field.get("name") or ""): field for field in existing_fields}
    merged = []
    for name in _CANONICAL_FIELDS:
        field = dict(by_name.get(name) or {})
        value = field_values.get(name) or str(field.get("value") or "").strip()
        field.update(
            {
                "name": name,
                "is_mandatory": bool(field.get("is_mandatory", name in _MANDATORY_FIELDS)),
                "is_grounded": bool(value),
                "value": value,
                "confidence": confidence_values.get(name, 0.0) if field_values.get(name) else field.get("confidence", 0),
            }
        )
        merged.append(field)
    return merged


def _fallback_state(raw_extraction: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    return {
        "normalized_extraction": copy.deepcopy(raw_extraction),
        "fallback_used": True,
        "validation_errors": errors,
    }


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _first_nonempty(*values: Any) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""
