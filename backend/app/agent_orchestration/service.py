from __future__ import annotations

import logging
from typing import Any

from .graph import build_generalized_verification_graph


LOGGER = logging.getLogger(__name__)


def normalize_extraction_payload(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    """Run the consolidated LangGraph/Gemini verification flow for extraction data."""
    if not isinstance(extraction_payload, dict):
        LOGGER.warning("GENERALIZED_VERIFICATION_FALLBACK reason=input_not_dict")
        return {}

    try:
        graph = build_generalized_verification_graph()
        graph.invoke({"extraction_payload": extraction_payload})
    except Exception as exc:
        LOGGER.warning("GENERALIZED_VERIFICATION_FALLBACK reason=graph_failed error=%s", exc)
        return extraction_payload

    LOGGER.info("GENERALIZED_VERIFICATION_GRAPH_ACCEPTED")
    return extraction_payload
