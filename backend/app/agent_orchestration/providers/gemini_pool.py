from __future__ import annotations

import logging
import os
import random
import time

LOGGER = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_POOL_MAX_RETRIES_PER_KEY = 1
GEMINI_POOL_SLEEP_SECONDS = 0.15
GEMINI_POOL_BACKOFF_MULTIPLIER = 2.0
GEMINI_POOL_JITTER_SECONDS = 0.05
GEMINI_POOL_STRATEGY_STAGE_PREFERRED = "stage_preferred"
GEMINI_POOL_STRATEGY_ROUND_ROBIN = "round_robin"

_POOL_ROTATION_INDEX = 0

_RATE_LIMIT_MARKERS = (
    "429",
    "resource_exhausted",
    "quota",
    "rate limit",
    "ratelimit",
)


class GeminiPoolConfigurationError(RuntimeError):
    """Raised when the Gemini pool cannot be configured safely."""


class GeminiPoolRateLimitError(RuntimeError):
    """Raised when all attempted Gemini key slots are rate limited."""


class GeminiPoolInvocationError(RuntimeError):
    """Raised when Gemini invocation fails for a non-rate-limit reason."""


def build_gemini_client(key_name: str = "primary"):
    key_slot = _normalize_key_name(key_name)
    api_key = _api_key_for_slot(key_slot)
    if not api_key:
        raise GeminiPoolConfigurationError(_missing_key_message(key_slot))

    ChatGoogleGenerativeAI = _load_chat_google_generative_ai()
    return ChatGoogleGenerativeAI(
        model=_read_model(),
        google_api_key=api_key,
        temperature=_read_float("GEMINI_TEMPERATURE", 0.0),
    )


def invoke_gemini_balanced(
    prompt_or_messages,
    *,
    preferred_key: str | None = None,
    schema: type | None = None,
    stage_name: str = "gemini",
):
    key_order = _key_order(preferred_key)
    configured_slots = [slot for slot in key_order if _api_key_for_slot(slot)]
    if not configured_slots:
        raise GeminiPoolConfigurationError("GEMINI_API_KEY is not configured")

    selected_first_slot = configured_slots[0]
    rate_limited_slots: list[str] = []
    for key_slot in configured_slots:
        try:
            return _invoke_with_retries(
                key_slot,
                prompt_or_messages,
                schema=schema,
                stage_name=stage_name,
                selected_first_slot=selected_first_slot,
            )
        except GeminiPoolRateLimitError:
            rate_limited_slots.append(key_slot)
            _log_safe_event(
                stage_name,
                key_slot,
                "fallback",
                attempt_number=None,
                selected_first_slot=selected_first_slot,
            )
            continue

    if rate_limited_slots:
        raise GeminiPoolRateLimitError("Gemini rate limit encountered for configured key slots")
    raise GeminiPoolConfigurationError("GEMINI_API_KEY is not configured")


def _invoke_with_retries(
    key_slot: str,
    prompt_or_messages,
    *,
    schema: type | None,
    stage_name: str,
    selected_first_slot: str,
):
    last_rate_limit = False
    for attempt_index in range(GEMINI_POOL_MAX_RETRIES_PER_KEY + 1):
        try:
            client = build_gemini_client(key_slot)
            invoker = client.with_structured_output(schema=schema, method="json_schema") if schema is not None else client
            response = invoker.invoke(prompt_or_messages)
            _log_safe_event(
                stage_name,
                key_slot,
                "success",
                attempt_number=attempt_index + 1,
                selected_first_slot=selected_first_slot,
            )
            return response
        except Exception as exc:
            exception_class = exc.__class__.__name__
            if _is_rate_limit_error(exc):
                last_rate_limit = True
                _log_safe_event(
                    stage_name,
                    key_slot,
                    "rate_limited",
                    exception_class=exception_class,
                    attempt_number=attempt_index + 1,
                    selected_first_slot=selected_first_slot,
                    warning=True,
                )
                if attempt_index < GEMINI_POOL_MAX_RETRIES_PER_KEY:
                    _sleep(_backoff_seconds(attempt_index))
                    continue
                break

            _log_safe_event(
                stage_name,
                key_slot,
                "non_rate_error",
                exception_class=exception_class,
                attempt_number=attempt_index + 1,
                selected_first_slot=selected_first_slot,
                warning=True,
            )
            raise GeminiPoolInvocationError("Gemini invocation failed") from exc

    if last_rate_limit:
        raise GeminiPoolRateLimitError("Gemini rate limit encountered for key slot")
    raise GeminiPoolInvocationError("Gemini invocation failed")


def _load_chat_google_generative_ai():
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - depends on optional local package
        raise GeminiPoolConfigurationError("langchain_google_genai is not installed") from exc
    return ChatGoogleGenerativeAI


def _api_key_for_slot(key_slot: str) -> str:
    if key_slot == "primary":
        return (
            os.getenv("GEMINI_API_KEY_PRIMARY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()
    if key_slot == "secondary":
        return (os.getenv("GEMINI_API_KEY_SECONDARY") or "").strip()
    raise GeminiPoolConfigurationError("Unsupported Gemini key slot")


def _key_order(preferred_key: str | None) -> list[str]:
    if _pool_strategy() == GEMINI_POOL_STRATEGY_ROUND_ROBIN:
        return _round_robin_key_order(preferred_key)
    return _stage_preferred_key_order(preferred_key)


def _stage_preferred_key_order(preferred_key: str | None) -> list[str]:
    if preferred_key is None or preferred_key == "primary":
        return ["primary", "secondary"]
    if preferred_key == "secondary":
        return ["secondary", "primary"]
    raise GeminiPoolConfigurationError("Unsupported Gemini key slot")


def _round_robin_key_order(preferred_key: str | None) -> list[str]:
    _stage_preferred_key_order(preferred_key)
    primary_configured = bool(_api_key_for_slot("primary"))
    secondary_configured = bool(_api_key_for_slot("secondary"))
    if primary_configured and secondary_configured:
        first_slot = _next_rotating_slot()
        alternate_slot = "secondary" if first_slot == "primary" else "primary"
        return [first_slot, alternate_slot]
    if primary_configured:
        return ["primary", "secondary"]
    if secondary_configured:
        return ["secondary", "primary"]
    return _stage_preferred_key_order(preferred_key)


def _next_rotating_slot() -> str:
    global _POOL_ROTATION_INDEX
    slot = "primary" if _POOL_ROTATION_INDEX % 2 == 0 else "secondary"
    _POOL_ROTATION_INDEX += 1
    return slot


def _reset_pool_rotation_for_tests() -> None:
    global _POOL_ROTATION_INDEX
    _POOL_ROTATION_INDEX = 0


def _normalize_key_name(key_name: str) -> str:
    if key_name in ("primary", "secondary"):
        return key_name
    raise GeminiPoolConfigurationError("Unsupported Gemini key slot")


def _missing_key_message(key_slot: str) -> str:
    if key_slot == "primary":
        return "GEMINI_API_KEY is not configured"
    return "GEMINI_API_KEY_SECONDARY is not configured"


def _read_model() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def _read_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _is_rate_limit_error(exc: BaseException) -> bool:
    safe_text = str(exc).lower()
    return any(marker in safe_text for marker in _RATE_LIMIT_MARKERS)


def _pool_strategy() -> str:
    strategy = (os.getenv("GEMINI_POOL_STRATEGY") or GEMINI_POOL_STRATEGY_STAGE_PREFERRED).strip().lower()
    if strategy == GEMINI_POOL_STRATEGY_ROUND_ROBIN:
        return GEMINI_POOL_STRATEGY_ROUND_ROBIN
    return GEMINI_POOL_STRATEGY_STAGE_PREFERRED


def _log_safe_event(
    stage_name: str,
    key_slot: str,
    outcome_category: str,
    *,
    attempt_number: int | None,
    selected_first_slot: str,
    exception_class: str | None = None,
    warning: bool = False,
) -> None:
    log = LOGGER.warning if warning else LOGGER.info
    extra = {
        "stage_name": stage_name,
        "selected_first_slot": selected_first_slot,
        "key_slot": key_slot,
        "outcome_category": outcome_category,
        "attempt_number": attempt_number,
    }
    if exception_class:
        extra["exception_class"] = exception_class
    log(
        "Gemini pool event",
        extra=extra,
    )


def _backoff_seconds(attempt_index: int) -> float:
    base_delay = GEMINI_POOL_SLEEP_SECONDS * (GEMINI_POOL_BACKOFF_MULTIPLIER ** attempt_index)
    return base_delay + _jitter()


def _jitter() -> float:
    return random.uniform(0.0, GEMINI_POOL_JITTER_SECONDS)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
