from __future__ import annotations

import logging
from typing import Any

from .graph import build_gemini_normalization_graph


LOGGER = logging.getLogger(__name__)


def normalize_extraction_payload(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    """Run LangGraph/Gemini normalization in memory and return canonical fields."""
    if not isinstance(extraction_payload, dict):
        LOGGER.warning("LLM_NORMALIZATION_FALLBACK reason=input_not_dict")
        return {}

    try:
        graph = build_gemini_normalization_graph()
        result = graph.invoke({"raw_extraction": extraction_payload})
    except Exception as exc:
        LOGGER.warning("LLM_NORMALIZATION_FALLBACK reason=graph_failed error=%s", exc)
        return extraction_payload

    normalized = result.get("normalized_extraction") if isinstance(result, dict) else None
    if not isinstance(normalized, dict):
        LOGGER.warning("LLM_NORMALIZATION_FALLBACK reason=missing_normalized_extraction")
        return extraction_payload

    if result.get("fallback_used"):
        LOGGER.warning(
            "LLM_NORMALIZATION_FALLBACK reason=validation_failed error_count=%s errors=%s",
            len(result.get("validation_errors") or []),
            result.get("validation_errors") or [],
        )
    else:
        LOGGER.info("LLM_NORMALIZATION_ACCEPTED")
    return normalized
