from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

class GeminiNormalizationState(TypedDict, total=False):
    raw_extraction: dict[str, Any]
    gemini_output: dict[str, Any]
    normalized_extraction: dict[str, Any]
    validation_errors: list[str]
    fallback_used: bool
