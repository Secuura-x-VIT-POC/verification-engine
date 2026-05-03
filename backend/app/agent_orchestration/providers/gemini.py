from __future__ import annotations

import json
import re
from typing import Any

from ..schemas import DynamicDocumentSchema
from .gemini_pool import GeminiPoolConfigurationError, build_gemini_client


def build_gemini_llm():
    try:
        return build_gemini_client("primary")
    except GeminiPoolConfigurationError as exc:
        if str(exc) == "GEMINI_API_KEY is not configured":
            raise RuntimeError("GEMINI_API_KEY is not configured") from exc
        raise RuntimeError(str(exc)) from exc


def _read_float(name: str, default: float) -> float:
    from .gemini_pool import _read_float as _pool_read_float

    return _pool_read_float(name, default)


def infer_dynamic_document_schema_from_evidence(evidence_graph: dict[str, Any], llm: Any | None = None) -> dict[str, Any]:
    """Ask Gemini to infer a schema and claim set from PP evidence graph only."""
    client = llm or build_gemini_llm()
    prompt = _dynamic_schema_prompt(evidence_graph)
    response = client.invoke(prompt)
    payload = _coerce_json_payload(response)
    return DynamicDocumentSchema.model_validate(payload).model_dump(mode="json")


def _dynamic_schema_prompt(evidence_graph: dict[str, Any]) -> str:
    minimized = dict(evidence_graph or {})
    minimized["evidence"] = list(minimized.get("evidence") or [])[:400]
    return (
        "Infer the document schema and extracted claims from this PP-ChatOCR evidence graph only. "
        "Return JSON only. Every claim must cite one or more evidence_ids from the graph. "
        "Do not invent document-specific templates or fixed field names; discover labels from evidence. "
        "Use this exact JSON shape: {document_type, document_subtype, issuing_entity, document_purpose, "
        "overall_confidence, claims:[{claim_id,label,value,normalized_value,data_type,importance,"
        "requires_verification,verification_intent,evidence_ids,page_number,confidence,reason}], "
        "missing_or_ambiguous_claims:[{label,reason,suggested_review_action}], warnings:[string]}.\n"
        f"Evidence graph:\n{json.dumps(minimized, default=str)}"
    )


def _coerce_json_payload(response: Any) -> dict[str, Any]:
    if isinstance(response, DynamicDocumentSchema):
        return response.model_dump(mode="json")
    if hasattr(response, "model_dump"):
        response = response.model_dump(mode="json")
    elif hasattr(response, "dict"):
        response = response.dict()
    if isinstance(response, dict):
        return response
    text = str(response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
