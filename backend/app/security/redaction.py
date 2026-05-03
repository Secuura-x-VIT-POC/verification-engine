from __future__ import annotations

import re
from typing import Any, Mapping


SAFE_LOG_KEYS = {
    "session_id",
    "stage",
    "status",
    "state",
    "reason_code",
    "reason_codes",
    "provider_id",
    "connector_id",
    "duration",
    "duration_ms",
    "error_category",
}

SENSITIVE_KEYS = {
    "name",
    "document",
    "document_bytes",
    "pdf",
    "raw_text",
    "raw_pdf_text",
    "pdf_text",
    "ocr_output",
    "ocr_text",
    "extracted_fields",
    "raw_value",
    "normalized_value",
    "input_payload",
    "raw_payload",
    "request_body",
    "response_body",
    "prompt",
    "response",
    "reviewer_note",
    "aadhaar",
    "pan",
    "email",
    "phone",
    "address",
}

EMAIL_RE = re.compile(r"^([^@\s])[^@\s]*(@[^@\s]+\.[^@\s]+)$")
DIGIT_RE = re.compile(r"\d")


def redact_value(value: Any, sensitivity: str = "HIGH") -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        return b"***REDACTED***"
    text = str(value).strip()
    if not text:
        return text

    normalized = str(sensitivity or "HIGH").upper()
    if normalized == "HIGH":
        return "***REDACTED***"
    if normalized == "MEDIUM":
        return _partial_mask(text)
    if normalized == "LOW":
        if len(text) <= 4:
            return "***"
        return f"{text[:2]}***{text[-2:]}"
    return "***REDACTED***"


def mask_identifier(value: Any) -> str:
    text = str(value or "").strip()
    compact_digits = re.sub(r"\D", "", text)
    if len(compact_digits) >= 4:
        return f"****{compact_digits[-4:]}"
    return _partial_mask(text)


def mask_email(value: Any) -> str:
    text = str(value or "").strip()
    match = EMAIL_RE.match(text)
    if not match:
        return _partial_mask(text)
    return f"{match.group(1)}***{match.group(2)}"


def mask_phone(value: Any) -> str:
    return mask_identifier(value)


def mask_name(value: Any) -> str:
    text = str(value or "").strip()
    words = text.split()
    if not words:
        return ""
    return " ".join(f"{word[0]}***" if word else "***" for word in words)


def hash_note(value: str) -> str:
    from ..audit.hmac_utils import generate_hmac_hex

    return generate_hmac_hex(str(value or "").strip())


def redact_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        normalized_key = str(key).lower()
        if normalized_key in SAFE_LOG_KEYS:
            redacted[key] = value
        elif _is_sensitive_key(normalized_key):
            redacted[key] = redact_value(value)
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_dict(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            redacted[key] = _mask_detected_pii(value)
    return redacted


def redact_log(message: Mapping[str, Any]) -> dict[str, Any]:
    return redact_dict(message)


def redact_log_context(message: Mapping[str, Any]) -> dict[str, Any]:
    return redact_log(message)


def safe_log_context(message: Mapping[str, Any]) -> dict[str, Any]:
    return redact_log(message)


def _is_sensitive_key(key: str) -> bool:
    return key in SENSITIVE_KEYS or any(token in key for token in ("raw_", "secret", "token", "password"))


def _mask_detected_pii(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if EMAIL_RE.match(text):
        return mask_email(text)
    if len(re.sub(r"\D", "", text)) >= 8 and DIGIT_RE.search(text):
        return mask_identifier(text)
    return value


def _partial_mask(text: str) -> str:
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"
