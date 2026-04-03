from __future__ import annotations

import re
from typing import Any

from .contracts import BoundingBox, ExtractedCredential


CATEGORY_KEYWORDS = {
    "passport": ("passport", "mrz", "travel document"),
    "license": ("license", "licence", "driver", "permit", "registration"),
    "address": ("address", "street", "city", "state", "postal", "postcode", "zip", "residence"),
    "financial": ("bank", "account", "iban", "ifsc", "salary", "income", "statement", "transaction", "swift"),
    "tax": ("tax", "pan", "tin", "gst", "vat", "ein", "ssn"),
    "academic": (
        "academic",
        "degree",
        "institution",
        "university",
        "college",
        "student",
        "transcript",
        "report card",
        "marksheet",
        "mark sheet",
        "grade report",
        "marks",
        "gpa",
        "cgpa",
        "credential",
        "certificate number",
    ),
    "certificate": ("certificate", "issuer", "certification", "completion", "awarded"),
    "identity": ("name", "identity", "identity number", "national id", "aadhaar", "date of birth", "dob"),
}

METADATA_ONLY_KEYWORDS = (
    "date",
    "issued on",
    "issue date",
    "expiry",
    "expires",
    "page",
    "watermark",
    "stamp",
    "seal",
    "signature",
    "qr",
    "barcode",
)

PII_KEYWORDS = (
    "name",
    "address",
    "passport",
    "license",
    "identity",
    "tax",
    "account",
    "iban",
    "swift",
    "dob",
    "birth",
    "aadhaar",
    "pan",
    "ssn",
)

IDENTIFIER_KEYWORDS = ("id", "identifier", "number", "registration", "roll", "account")


def build_extracted_credentials(extraction_payload: dict[str, Any] | None) -> list[ExtractedCredential]:
    if not extraction_payload:
        return []

    document_type = str(extraction_payload.get("document_type") or "unknown")
    extraction_method = _resolve_extraction_method(extraction_payload)
    credentials: list[ExtractedCredential] = []

    for index, entry in enumerate(_iter_field_entries(extraction_payload), start=1):
        label = entry["label"]
        raw_value = entry["value"]
        normalized_value = normalize_value(raw_value)
        category = classify_credential_category(
            label=label,
            key=entry["key"],
            normalized_value=normalized_value,
            document_type=document_type,
        )
        requires_verification, verification_reason = determine_verification_requirement(
            label=label,
            key=entry["key"],
            category=category,
            normalized_value=normalized_value,
        )
        bounding_box = _normalize_bounding_box(entry["bounding_box"])
        page = bounding_box.page if bounding_box is not None else None
        credentials.append(
            ExtractedCredential(
                credential_id=_build_credential_id(entry["key"], index),
                label=label,
                category=category,
                value=raw_value,
                normalized_value=normalized_value,
                source_text=entry["source_text"],
                confidence=_coerce_confidence(entry["confidence"]),
                page=page,
                bounding_box=bounding_box,
                is_pii=is_pii_field(
                    label=label,
                    key=entry["key"],
                    category=category,
                    normalized_value=normalized_value,
                ),
                requires_verification=requires_verification,
                verification_reason=verification_reason,
                extraction_method=entry["extraction_method"] or extraction_method,
            )
        )

    return credentials


def classify_credential_category(
    *,
    label: str,
    key: str | None = None,
    normalized_value: str | None = None,
    document_type: str | None = None,
) -> str:
    primary_haystack = " ".join(
        part
        for part in (
            (key or "").replace("_", " "),
            label.lower(),
            (normalized_value or "").lower(),
        )
        if part
    )
    document_context = (document_type or "").replace("_", " ").lower()

    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["passport"]):
        return "passport"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["license"]):
        return "license"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["address"]):
        return "address"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["financial"]):
        return "financial"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["tax"]):
        return "tax"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["academic"]):
        return "academic"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["certificate"]):
        return "certificate"
    if _contains_any_keyword(primary_haystack, CATEGORY_KEYWORDS["identity"]):
        return "identity"

    if (
        any(token in document_context for token in ("academic", "transcript", "credential", "report card", "marksheet", "mark sheet", "grade report"))
        and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS)
    ):
        return "academic"
    if ("passport" in document_context or "travel" in document_context) and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "passport"
    if ("license" in document_context or "licence" in document_context) and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "license"
    if "address" in document_context and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "address"
    if ("bank" in document_context or "financial" in document_context) and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "financial"
    if "tax" in document_context and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "tax"
    if ("identity" in document_context or "personal" in document_context) and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "identity"
    return "unknown"


def determine_verification_requirement(
    *,
    label: str,
    key: str | None = None,
    category: str,
    normalized_value: str | None = None,
) -> tuple[bool, str]:
    if not normalized_value:
        return False, "No extracted value is available to verify."

    haystack = " ".join(part for part in ((key or "").lower(), label.lower()) if part)
    if _contains_any_keyword(haystack, METADATA_ONLY_KEYWORDS):
        return False, "This appears to be supporting metadata rather than a standalone verifiable credential."

    if category in {"identity", "address", "passport", "license", "academic", "financial", "tax", "certificate"}:
        return True, f"Category '{category}' is mapped to a deterministic verifier route."

    if _contains_any_keyword(haystack, IDENTIFIER_KEYWORDS):
        return True, "The field looks like an identifier and should be reviewed through manual verification."

    return False, "No deterministic verifier route is currently available for this extracted field."


def is_pii_field(
    *,
    label: str,
    key: str | None = None,
    category: str,
    normalized_value: str | None = None,
) -> bool:
    if category in {"identity", "address", "passport", "license", "financial", "tax"}:
        return True

    haystack = " ".join(part for part in ((key or "").lower(), label.lower(), (normalized_value or "").lower()) if part)
    return _contains_any_keyword(haystack, PII_KEYWORDS)


def normalize_value(value: Any) -> str | None:
    if value is None:
        return None

    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _iter_field_entries(extraction_payload: dict[str, Any]) -> list[dict[str, Any]]:
    field_details = extraction_payload.get("field_details")
    if isinstance(field_details, list) and field_details:
        entries = []
        for index, detail in enumerate(field_details, start=1):
            key = str(detail.get("key") or detail.get("name") or f"field_{index}")
            bounding_boxes = detail.get("bounding_boxes") or []
            entries.append(
                {
                    "key": key,
                    "label": str(detail.get("label") or _humanize_key(key)),
                    "value": detail.get("value"),
                    "confidence": detail.get("confidence"),
                    "bounding_box": (bounding_boxes[0] if bounding_boxes else None),
                    "source_text": _coerce_source_text(detail.get("source_text"), detail.get("value")),
                    "extraction_method": detail.get("extraction_method"),
                }
            )
        return entries

    raw_fields = extraction_payload.get("fields") or {}
    confidence_map = extraction_payload.get("confidence") or {}
    bounding_boxes = extraction_payload.get("bounding_boxes") or {}
    entries = []
    for index, (key, raw_value) in enumerate(raw_fields.items(), start=1):
        detail = raw_value if isinstance(raw_value, dict) else {}
        value = detail.get("value") if detail else raw_value
        entries.append(
            {
                "key": str(key or f"field_{index}"),
                "label": _humanize_key(str(key or f"field_{index}")),
                "value": value,
                "confidence": detail.get("confidence", confidence_map.get(key)),
                "bounding_box": _first_box(detail.get("bounding_boxes")) or bounding_boxes.get(key),
                "source_text": _coerce_source_text(detail.get("source_text"), value),
                "extraction_method": detail.get("extraction_method"),
            }
        )
    return entries


def _build_credential_id(key: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    if not slug:
        slug = "credential"
    return f"{slug}-{index}"


def _humanize_key(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _coerce_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _coerce_source_text(source_text: Any, fallback_value: Any) -> str | None:
    resolved = source_text if source_text not in (None, "") else fallback_value
    if resolved in (None, ""):
        return None
    return str(resolved)


def _resolve_extraction_method(extraction_payload: dict[str, Any]) -> str:
    if extraction_payload.get("used_ocr") or extraction_payload.get("ocr_used"):
        return "ocr"
    if extraction_payload.get("field_details"):
        return "structured_extraction"
    return "rule_based"


def _first_box(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value:
        candidate = value[0]
        return candidate if isinstance(candidate, dict) else None
    if isinstance(value, dict):
        return value
    return None


def _normalize_bounding_box(value: Any) -> BoundingBox | None:
    if not isinstance(value, dict):
        return None

    return BoundingBox(
        page=_coerce_int(value.get("page")),
        x0=_coerce_float(value.get("x0")),
        y0=_coerce_float(value.get("y0")),
        x1=_coerce_float(value.get("x1")),
        y1=_coerce_float(value.get("y1")),
    )


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contains_any_keyword(haystack: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_keyword(haystack, keyword) for keyword in keywords)


def _contains_keyword(haystack: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, haystack) is not None
