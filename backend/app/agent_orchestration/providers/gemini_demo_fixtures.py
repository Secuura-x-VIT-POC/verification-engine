from __future__ import annotations

import os
from typing import Any

from ..schemas import (
    GeminiCredentialGroupCollection,
    GeminiDocumentUnderstanding,
    SemanticNormalizedClaimCollection,
)


def gemini_demo_fixture_enabled() -> bool:
    return _read_bool("GEMINI_DEMO_FIXTURE_ENABLED", False)


def build_gemini_demo_fixture(
    *,
    stage_name: str,
    schema,
    fallback_model: Any | None = None,
):
    if not gemini_demo_fixture_enabled():
        return None
    if stage_name == "gemini_document_understanding" and schema is GeminiDocumentUnderstanding:
        return _document_understanding_fixture(fallback_model)
    if stage_name == "gemini_field_normalization" and schema is SemanticNormalizedClaimCollection:
        return SemanticNormalizedClaimCollection(claims=[])
    if stage_name == "gemini_credential_grouping" and schema is GeminiCredentialGroupCollection:
        return _credential_grouping_fixture(fallback_model)
    return None


def _document_understanding_fixture(fallback_model: Any | None) -> GeminiDocumentUnderstanding:
    base = _safe_model_payload(fallback_model)
    return GeminiDocumentUnderstanding(
        document_type=str(base.get("document_type") or "unknown_document"),
        document_type_confidence=float(base.get("document_type_confidence") or 0.0),
        likely_claim_types=_safe_string_list(base.get("likely_claim_types")) or ["generic_claim"],
        credential_group_hints=_safe_string_list(base.get("credential_group_hints")),
        mandatory_fields=_safe_string_list(base.get("mandatory_fields")),
        optional_fields=_safe_string_list(base.get("optional_fields")),
        safety_flags=_safe_string_list(base.get("safety_flags")),
        ambiguity_flags=_safe_string_list(base.get("ambiguity_flags")),
        summary="Demo fixture fallback used after Gemini rate limiting.",
        explanation="Gemini was rate limited; sanitized deterministic document context remained authoritative.",
        unsafe_or_malformed=bool(base.get("unsafe_or_malformed", False)),
        grounding_confidence=float(base.get("grounding_confidence") or 0.0),
        matching_score=0.0,
        visual_match_probability=0.0,
        risk_flags=_safe_string_list(base.get("risk_flags")),
    )


def _credential_grouping_fixture(fallback_model: Any | None) -> GeminiCredentialGroupCollection:
    if isinstance(fallback_model, GeminiCredentialGroupCollection):
        return fallback_model
    try:
        return GeminiCredentialGroupCollection.model_validate(_safe_model_payload(fallback_model))
    except Exception:
        return GeminiCredentialGroupCollection(groups=[])


def _safe_model_payload(model: Any | None) -> dict[str, Any]:
    if model is None:
        return {}
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    elif hasattr(model, "dict"):
        payload = model.dict()
    else:
        payload = model
    return payload if isinstance(payload, dict) else {}


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _safe_public_label(item)]


def _safe_public_label(value: Any) -> bool:
    text = str(value or "")
    upper_text = text.upper()
    return not any(marker in upper_text for marker in ("RAW", "SECRET", "PRIVATE", "API_KEY", "TOKEN"))


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}
