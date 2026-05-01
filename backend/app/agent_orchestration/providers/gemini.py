from __future__ import annotations

import os


def build_gemini_llm():
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - depends on optional local package
        raise RuntimeError("langchain_google_genai is not installed") from exc

    temperature = _read_float("GEMINI_TEMPERATURE", 0.0)
    return ChatGoogleGenerativeAI(
        model=(os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        google_api_key=api_key,
        temperature=temperature,
    )


def _read_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default
