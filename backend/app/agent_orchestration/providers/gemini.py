from __future__ import annotations

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
