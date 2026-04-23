from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes import (
    build_credential_grouping_node,
    build_document_understanding_node,
    build_explanation_synthesis_node,
    build_input_normalization_node,
    build_output_consolidation_node,
    build_route_recommendation_node,
)
from .state import AgentGraphState, GeminiNormalizationState


LOGGER = logging.getLogger(__name__)

_CANONICAL_FIELDS = ("name", "institution", "credential", "date", "id")
_MANDATORY_FIELDS = {"name", "institution", "credential", "id"}


def build_agent_graph(provider):
    # DEPRECATED AGENT GRAPH:
    # This graph powers legacy pass A/pass B agent artifacts and is kept only
    # for migration compatibility. The worker path uses
    # build_gemini_normalization_graph(), which is stateless and in-memory.
    input_node = "node_input_normalization"
    understanding_node = "node_document_understanding"
    grouping_node = "node_credential_grouping"
    routing_node = "node_route_recommendation"
    explanation_node = "node_explanation_synthesis"
    consolidation_node = "node_output_consolidation"

    graph = StateGraph(AgentGraphState)
    graph.add_node(input_node, build_input_normalization_node())
    graph.add_node(understanding_node, build_document_understanding_node(provider))
    graph.add_node(grouping_node, build_credential_grouping_node(provider))
    graph.add_node(routing_node, build_route_recommendation_node(provider))
    graph.add_node(explanation_node, build_explanation_synthesis_node(provider))
    graph.add_node(consolidation_node, build_output_consolidation_node())
    graph.add_edge(START, input_node)
    graph.add_edge(input_node, understanding_node)
    graph.add_edge(understanding_node, grouping_node)
    graph.add_edge(grouping_node, routing_node)
    graph.add_edge(routing_node, explanation_node)
    graph.add_edge(explanation_node, consolidation_node)
    graph.add_edge(consolidation_node, END)
    return graph.compile()


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
        response = llm.invoke(_build_normalization_prompt(raw_extraction))
        parsed_output = _parse_json_response(getattr(response, "content", response))
        return {
            "gemini_output": parsed_output,
            "fallback_used": False,
            "validation_errors": [],
        }
    except Exception as exc:
        LOGGER.warning("GEMINI_NORMALIZATION_FALLBACK error=%s", exc)
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

    fields = gemini_output.get("fields")
    connector_input = gemini_output.get("connector_input")
    if not isinstance(fields, dict):
        errors.append("Gemini output missing fields object")
    if connector_input is not None and not isinstance(connector_input, dict):
        errors.append("Gemini connector_input is not an object")
    if not any(str((fields or {}).get(name) or "").strip() for name in _CANONICAL_FIELDS):
        errors.append("Gemini output contains no canonical field values")

    if errors:
        return _fallback_state(raw_extraction, errors)

    try:
        normalized = _merge_normalized_output(raw_extraction, gemini_output)
        return {
            "normalized_extraction": normalized,
            "fallback_used": False,
            "validation_errors": [],
        }
    except Exception as exc:
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
