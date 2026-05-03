from __future__ import annotations

import re
from typing import Any

from .schemas import SemanticNormalizedClaim, SemanticNormalizedClaimCollection


def normalize_claims_semantically(
    claims: list[dict[str, Any]],
    document_profile: dict[str, Any] | None = None,
    llm: Any | None = None,
) -> list[dict[str, Any]]:
    """Normalize claim meaning without making verifier or trust decisions."""
    sanitized_claims = [claim for claim in claims if isinstance(claim, dict)]
    if llm is not None and sanitized_claims:
        try:
            prompt_payload = {
                "claims": [_claim_without_raw_value(claim) for claim in sanitized_claims],
                "document_profile": dict(document_profile or {}),
            }
            response = llm.invoke(prompt_payload)
            collection = _validate_llm_response(response)
            normalized = []
            for claim in collection.claims:
                payload = claim.model_dump(mode="json")
                payload["normalization_source"] = "gemini"
                payload["source"] = "gemini"
                normalized.append(_without_raw_value(payload))
            return normalized
        except Exception:
            pass

    return [
        _without_raw_value(_fallback_claim(index, claim).model_dump(mode="json"))
        for index, claim in enumerate(sanitized_claims, start=1)
    ]


def safe_normalized_string(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _validate_llm_response(response: Any) -> SemanticNormalizedClaimCollection:
    if isinstance(response, SemanticNormalizedClaimCollection):
        return response
    if isinstance(response, list):
        return SemanticNormalizedClaimCollection(claims=response)
    if hasattr(response, "model_dump"):
        response = response.model_dump(mode="json")
    elif hasattr(response, "dict"):
        response = response.dict()

    if isinstance(response, dict) and "claims" in response:
        return SemanticNormalizedClaimCollection.model_validate(response)
    if isinstance(response, dict):
        return SemanticNormalizedClaimCollection(claims=[response])
    raise ValueError("Expected structured semantic claims")


def _fallback_claim(index: int, claim: dict[str, Any]) -> SemanticNormalizedClaim:
    label = safe_normalized_string(
        claim.get("label")
        or claim.get("canonical_label")
        or claim.get("field_id")
        or claim.get("name")
        or claim.get("category")
    )
    category = safe_normalized_string(claim.get("claim_type") or claim.get("category"))
    raw_value = claim.get("raw_value") if "raw_value" in claim else claim.get("value")
    normalized_value = safe_normalized_string(
        claim.get("normalized_value") if claim.get("normalized_value") not in (None, "") else raw_value
    )
    return SemanticNormalizedClaim(
        claim_id=safe_normalized_string(claim.get("claim_id") or claim.get("candidate_id") or f"claim-{index}"),
        field_id=safe_normalized_string(claim.get("field_id") or claim.get("key") or claim.get("name")) or None,
        raw_value=None,
        label=label or None,
        value_preview=_value_preview(normalized_value),
        normalized_value=normalized_value,
        claim_type=category or _claim_type_from_label(label),
        canonical_label=label or None,
        document_context=safe_normalized_string(claim.get("document_context") or claim.get("category")) or None,
        confidence=_coerce_confidence(claim.get("confidence"), default=0.5),
        source="deterministic_fallback",
        normalization_source="deterministic_fallback",
        requires_verification=bool(claim.get("requires_verification", True)),
        reason=safe_normalized_string(claim.get("reason") or claim.get("verification_reason")) or None,
        reason_codes=list(claim.get("reason_codes") or []),
        ambiguity_flags=list(claim.get("ambiguity_flags") or []),
    )


def _claim_type_from_label(label: str) -> str:
    normalized = safe_normalized_string(label).lower().replace(" ", "_")
    return normalized or "generic_claim"


def _coerce_confidence(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _claim_without_raw_value(claim: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(claim)
    sanitized.pop("raw_value", None)
    sanitized.pop("source_text", None)
    return sanitized


def _without_raw_value(claim: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(claim)
    sanitized.pop("raw_value", None)
    return sanitized


def _value_preview(value: str) -> str | None:
    text = safe_normalized_string(value)
    if not text:
        return None
    if len(text) <= 32:
        return text
    return f"{text[:29].rstrip()}..."
