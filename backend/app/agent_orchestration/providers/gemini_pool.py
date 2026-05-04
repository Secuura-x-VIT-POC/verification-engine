from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_POOL_MAX_RETRIES_PER_KEY = 0
GEMINI_POOL_SLEEP_SECONDS = 0.15
GEMINI_POOL_BACKOFF_MULTIPLIER = 2.0
GEMINI_POOL_JITTER_SECONDS = 0.05
GEMINI_POOL_STRATEGY_STAGE_PREFERRED = "stage_preferred"
GEMINI_POOL_STRATEGY_ROUND_ROBIN = "round_robin"

_POOL_ROTATION_INDEX = 0
_COOLDOWN_UNTIL_BY_FINGERPRINT: dict[str, float] = {}

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


@dataclass(frozen=True)
class GeminiKeyEntry:
    slot: str
    index: int
    key: str
    fingerprint: str


def build_gemini_client(key_name: str = "primary"):
    entry = _entry_for_slot(_normalize_key_name(key_name))

    ChatGoogleGenerativeAI = _load_chat_google_generative_ai()
    return _construct_chat_google_generative_ai(ChatGoogleGenerativeAI, entry.key)


def invoke_gemini_balanced(
    prompt_or_messages,
    *,
    preferred_key: str | None = None,
    schema: type | None = None,
    stage_name: str = "gemini",
):
    configured_entries = _key_order(preferred_key)
    if not configured_entries:
        raise GeminiPoolConfigurationError("GEMINI_API_KEY is not configured")

    selected_first_entry = configured_entries[0]
    rate_limited_slots: list[str] = []
    for entry in configured_entries:
        if _is_in_cooldown(entry):
            rate_limited_slots.append(entry.slot)
            _log_safe_event(
                stage_name,
                entry,
                "cooling_down",
                attempt_number=None,
                selected_first_entry=selected_first_entry,
            )
            continue
        try:
            return _invoke_with_retries(
                entry,
                prompt_or_messages,
                schema=schema,
                stage_name=stage_name,
                selected_first_entry=selected_first_entry,
            )
        except GeminiPoolRateLimitError:
            rate_limited_slots.append(entry.slot)
            _log_safe_event(
                stage_name,
                entry,
                "fallback",
                attempt_number=None,
                selected_first_entry=selected_first_entry,
            )
            continue

    if rate_limited_slots:
        raise GeminiPoolRateLimitError("Gemini rate limit encountered for configured key slots")
    raise GeminiPoolConfigurationError("GEMINI_API_KEY is not configured")


def _invoke_with_retries(
    entry: GeminiKeyEntry,
    prompt_or_messages,
    *,
    schema: type | None,
    stage_name: str,
    selected_first_entry: GeminiKeyEntry,
):
    last_rate_limit = False
    for attempt_index in range(GEMINI_POOL_MAX_RETRIES_PER_KEY + 1):
        try:
            client = _construct_chat_google_generative_ai(_load_chat_google_generative_ai(), entry.key)
            invoker = _structured_invoker(client, schema) if schema is not None else client
            response = invoker.invoke(prompt_or_messages)
            _log_safe_event(
                stage_name,
                entry,
                "success",
                attempt_number=attempt_index + 1,
                selected_first_entry=selected_first_entry,
            )
            return response
        except Exception as exc:
            exception_class = exc.__class__.__name__
            if _is_rate_limit_error(exc):
                last_rate_limit = True
                _log_safe_event(
                    stage_name,
                    entry,
                    "rate_limited",
                    exception_class=exception_class,
                    attempt_number=attempt_index + 1,
                    selected_first_entry=selected_first_entry,
                    warning=True,
                )
                _mark_cooling_down(entry)
                if attempt_index < GEMINI_POOL_MAX_RETRIES_PER_KEY:
                    _sleep(_backoff_seconds(attempt_index))
                    continue
                break

            _log_safe_event(
                stage_name,
                entry,
                "non_rate_error",
                exception_class=exception_class,
                attempt_number=attempt_index + 1,
                selected_first_entry=selected_first_entry,
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


def _construct_chat_google_generative_ai(ChatGoogleGenerativeAI, api_key: str):
    kwargs = {
        "model": _read_model(),
        "google_api_key": api_key,
        "temperature": _read_float("GEMINI_TEMPERATURE", 0.0),
        "timeout": _read_int("GEMINI_PROVIDER_TIMEOUT_SECONDS", 45),
        "max_retries": _read_int("GEMINI_PROVIDER_MAX_RETRIES", 0, minimum=0, maximum=2),
    }
    try:
        return ChatGoogleGenerativeAI(**kwargs)
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return ChatGoogleGenerativeAI(
            model=kwargs["model"],
            google_api_key=kwargs["google_api_key"],
            temperature=kwargs["temperature"],
        )


def _structured_invoker(client, schema: type):
    try:
        return client.with_structured_output(schema=schema, method="json_schema")
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return client.with_structured_output(schema)


def _api_key_for_slot(key_slot: str) -> str:
    try:
        return _entry_for_slot(key_slot).key
    except GeminiPoolConfigurationError:
        return ""


def _key_order(preferred_key: str | None) -> list[GeminiKeyEntry]:
    if _pool_strategy() == GEMINI_POOL_STRATEGY_ROUND_ROBIN:
        return _round_robin_key_order(preferred_key)
    return _stage_preferred_key_order(preferred_key)


def _stage_preferred_key_order(preferred_key: str | None) -> list[GeminiKeyEntry]:
    entries = _configured_key_entries()
    if not entries:
        return []
    if preferred_key is None or preferred_key == "primary":
        preferred_slots = ["primary"]
    elif preferred_key == "secondary":
        preferred_slots = ["secondary"]
    else:
        raise GeminiPoolConfigurationError("Unsupported Gemini key slot")
    preferred = [entry for entry in entries if entry.slot in preferred_slots]
    others = [entry for entry in entries if entry.slot not in preferred_slots]
    return preferred + others


def _round_robin_key_order(preferred_key: str | None) -> list[GeminiKeyEntry]:
    _stage_preferred_key_order(preferred_key)
    entries = _configured_key_entries()
    if len(entries) <= 1:
        return entries
    first_index = _next_rotating_index(len(entries))
    return entries[first_index:] + entries[:first_index]


def _next_rotating_index(entry_count: int) -> int:
    global _POOL_ROTATION_INDEX
    index = _POOL_ROTATION_INDEX % max(entry_count, 1)
    _POOL_ROTATION_INDEX += 1
    return index


def _reset_pool_rotation_for_tests() -> None:
    global _POOL_ROTATION_INDEX
    _POOL_ROTATION_INDEX = 0
    _COOLDOWN_UNTIL_BY_FINGERPRINT.clear()


def _normalize_key_name(key_name: str) -> str:
    if key_name in ("primary", "secondary") or key_name.startswith("key_"):
        return key_name
    raise GeminiPoolConfigurationError("Unsupported Gemini key slot")


def _missing_key_message(key_slot: str) -> str:
    if key_slot == "primary":
        return "GEMINI_API_KEY is not configured"
    return "GEMINI_API_KEY_SECONDARY is not configured"


def _entry_for_slot(key_slot: str) -> GeminiKeyEntry:
    for entry in _configured_key_entries():
        if entry.slot == key_slot:
            return entry
    raise GeminiPoolConfigurationError(_missing_key_message(key_slot))


def _configured_key_entries() -> list[GeminiKeyEntry]:
    raw_candidates: list[tuple[str, str]] = []
    raw_candidates.extend(("key_%d" % index, value.strip()) for index, value in enumerate((os.getenv("GEMINI_API_KEYS") or "").split(",")) if value.strip())
    raw_candidates.extend(
        [
            ("primary", os.getenv("GEMINI_API_KEY_PRIMARY") or ""),
            ("primary", os.getenv("GEMINI_API_KEY") or ""),
            ("primary", os.getenv("GOOGLE_API_KEY") or ""),
            ("primary", os.getenv("GEMINI_API_KEY_1") or ""),
            ("secondary", os.getenv("GEMINI_API_KEY_SECONDARY") or ""),
            ("secondary", os.getenv("GEMINI_API_KEY_2") or ""),
        ]
    )

    entries: list[GeminiKeyEntry] = []
    seen: set[str] = set()
    for slot, raw_key in raw_candidates:
        key = str(raw_key or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if slot.startswith("key_"):
            slot = "primary" if not entries else "secondary" if len(entries) == 1 else slot
        entries.append(GeminiKeyEntry(slot=slot, index=len(entries), key=key, fingerprint=_fingerprint(key)))
    return entries


def _fingerprint(key: str) -> str:
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _is_in_cooldown(entry: GeminiKeyEntry) -> bool:
    return _COOLDOWN_UNTIL_BY_FINGERPRINT.get(entry.fingerprint, 0.0) > time.monotonic()


def _mark_cooling_down(entry: GeminiKeyEntry) -> None:
    _COOLDOWN_UNTIL_BY_FINGERPRINT[entry.fingerprint] = time.monotonic() + _read_int(
        "GEMINI_POOL_COOLDOWN_SECONDS",
        60,
        minimum=0,
        maximum=3600,
    )


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


def _read_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        value = default
    else:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


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
    entry: GeminiKeyEntry,
    outcome_category: str,
    *,
    attempt_number: int | None,
    selected_first_entry: GeminiKeyEntry,
    exception_class: str | None = None,
    warning: bool = False,
) -> None:
    log = LOGGER.warning if warning else LOGGER.info
    extra = {
        "stage_name": stage_name,
        "selected_first_slot": selected_first_entry.slot,
        "selected_first_key_index": selected_first_entry.index,
        "key_slot": entry.slot,
        "key_index": entry.index,
        "key_fingerprint": entry.fingerprint,
        "outcome_category": outcome_category,
        "attempt_number": attempt_number,
    }
    if exception_class:
        extra["exception_class"] = exception_class
    log(
        "Gemini pool selected key index=%s outcome=%s",
        entry.index,
        outcome_category,
        extra=extra,
    )


def _backoff_seconds(attempt_index: int) -> float:
    base_delay = GEMINI_POOL_SLEEP_SECONDS * (GEMINI_POOL_BACKOFF_MULTIPLIER ** attempt_index)
    return base_delay + _jitter()


def _jitter() -> float:
    return random.uniform(0.0, GEMINI_POOL_JITTER_SECONDS)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
