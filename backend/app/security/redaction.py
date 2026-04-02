import re
from typing import Any, Dict

# Fields that must NEVER appear in logs
SENSITIVE_KEYS = {
    "name",
    "document",
    "document_bytes",
    "pdf",
    "raw_text",
    "ocr_output",
    "extracted_fields",
    "id",
    "aadhaar",
    "pan",
    "email"
}


def redact_value(value: Any) -> Any:
    """
    Redact sensitive values.
    """
    if isinstance(value, str):
        # mask long strings
        if len(value) > 10:
            return value[:3] + "***REDACTED***"
        return "***REDACTED***"

    if isinstance(value, bytes):
        return b"***REDACTED***"

    return "***REDACTED***"


def redact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively redact sensitive fields.
    """
    redacted = {}

    for key, value in data.items():

        if key.lower() in SENSITIVE_KEYS:
            redacted[key] = redact_value(value)

        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)

        elif isinstance(value, list):
            redacted[key] = [
                redact_dict(v) if isinstance(v, dict) else redact_value(v)
                for v in value
            ]

        else:
            redacted[key] = value

    return redacted


def redact_log(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entry function used before logging anything.
    """
    return redact_dict(message)