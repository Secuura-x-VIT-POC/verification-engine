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

    document_type = _resolve_document_type(extraction_payload)
    extraction_method = _resolve_extraction_method(extraction_payload)
    credentials: list[ExtractedCredential] = []

    for index, entry in enumerate(_iter_generalized_entries(extraction_payload), start=1):
        label = entry["label"]
        raw_value = entry["value"]
        source_category = entry.get("source_category")
        normalized_value = normalize_value(entry.get("normalized_value") or raw_value)
        if not normalized_value and not _coerce_source_text(entry["source_text"], raw_value):
            continue
        category = classify_credential_category(
            label=label,
            key=entry["key"],
            source_category=source_category,
            normalized_value=normalized_value,
            document_type=document_type,
        )
        explicit_requires_verification = entry.get("requires_verification")
        explicit_verification_reason = entry.get("verification_reason")
        if explicit_requires_verification is None:
            requires_verification, verification_reason = determine_verification_requirement(
                label=label,
                key=entry["key"],
                category=category,
                normalized_value=normalized_value,
            )
        else:
            requires_verification = bool(explicit_requires_verification)
            verification_reason = explicit_verification_reason or (
                "This extracted credential is marked for verification in the generalized analysis payload."
                if requires_verification
                else "The generalized analysis payload marked this field as out of scope for direct verification."
            )
        bounding_box = _normalize_bounding_box(entry["bounding_box"])
        page = _coerce_int(entry.get("page"))
        if page is None and bounding_box is not None:
            page = bounding_box.page
        credentials.append(
            ExtractedCredential(
                credential_id=str(entry.get("credential_id") or _build_credential_id(entry["key"], index)),
                label=label,
                category=category,
                value=raw_value,
                normalized_value=normalized_value,
                source_text=entry["source_text"],
                confidence=_coerce_confidence(entry["confidence"]),
                page=page,
                bounding_box=bounding_box,
                is_pii=(
                    bool(entry["is_pii"])
                    if entry.get("is_pii") is not None
                    else is_pii_field(
                        label=label,
                        key=entry["key"],
                        category=category,
                        normalized_value=normalized_value,
                    )
                ),
                requires_verification=requires_verification,
                verification_reason=verification_reason,
                extraction_method=entry["extraction_method"] or extraction_method,
            )
        )

    return _dedupe_credentials(credentials)


def classify_credential_category(
    *,
    label: str,
    key: str | None = None,
    source_category: str | None = None,
    normalized_value: str | None = None,
    document_type: str | None = None,
) -> str:
    primary_haystack = " ".join(
        part
        for part in (
            (key or "").replace("_", " "),
            (source_category or "").replace("_", " "),
            label.lower(),
            (normalized_value or "").lower(),
        )
        if part
    )
    document_context = (document_type or "").replace("_", " ").lower()
    normalized_source_category = (source_category or "").strip().lower()

    if normalized_source_category in {"person_name", "date_of_birth", "national_identifier"}:
        return "identity"
    if normalized_source_category == "address":
        return "address"
    if normalized_source_category in {"passport_number", "passport_identifier"}:
        return "passport"
    if normalized_source_category in {"license_number", "license_identifier"}:
        return "license"
    if normalized_source_category in {"tax_identifier"}:
        return "tax"
    if normalized_source_category in {"email", "phone_number"}:
        return "identity"
    if normalized_source_category in {"issuer", "credential_title", "program_name", "program_branch", "registration_number", "score"}:
        if any(
            token in document_context
            for token in ("academic", "transcript", "credential", "report card", "marksheet", "mark sheet", "grade report")
        ):
            return "academic"
        if "certificate" in document_context:
            return "certificate"

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


def _iter_generalized_entries(extraction_payload: dict[str, Any]) -> list[dict[str, Any]]:
    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    generalized_credentials = generalized_analysis.get("generalized_credentials_payload")
    if isinstance(generalized_credentials, list) and generalized_credentials:
        entries = []
        for index, credential in enumerate(generalized_credentials, start=1):
            if not isinstance(credential, dict):
                continue
            label = str(credential.get("label") or f"Credential {index}")
            key = str(credential.get("credential_id") or _slug(label) or f"credential_{index}")
            entries.append(
                {
                    "credential_id": credential.get("credential_id"),
                    "key": key,
                    "label": label,
                    "value": credential.get("value"),
                    "normalized_value": credential.get("normalized_value"),
                    "confidence": credential.get("confidence"),
                    "bounding_box": credential.get("bounding_box"),
                    "page": credential.get("page"),
                    "source_text": _coerce_source_text(credential.get("source_text"), credential.get("value")),
                    "extraction_method": credential.get("extraction_method"),
                    "source_category": credential.get("category"),
                    "is_pii": credential.get("is_pii"),
                    "requires_verification": credential.get("requires_verification"),
                    "verification_reason": credential.get("verification_reason"),
                }
            )
        return entries

    field_candidates = extraction_payload.get("field_candidates")
    if isinstance(field_candidates, list) and field_candidates:
        entries = []
        for index, candidate in enumerate(field_candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            label = str(candidate.get("label") or f"Credential {index}")
            key = str(candidate.get("candidate_id") or _slug(label) or f"candidate_{index}")
            entries.append(
                {
                    "credential_id": candidate.get("candidate_id"),
                    "key": key,
                    "label": label,
                    "value": candidate.get("raw_value"),
                    "normalized_value": candidate.get("normalized_value"),
                    "confidence": candidate.get("confidence"),
                    "bounding_box": candidate.get("bounding_box"),
                    "page": candidate.get("page"),
                    "source_text": _coerce_source_text(candidate.get("source_text"), candidate.get("raw_value")),
                    "extraction_method": candidate.get("extraction_method"),
                    "source_category": candidate.get("category"),
                    "is_pii": candidate.get("is_pii"),
                    "requires_verification": candidate.get("requires_verification"),
                    "verification_reason": candidate.get("verification_reason"),
                }
            )
        return entries

    return []


def _build_credential_id(key: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    if not slug:
        slug = "credential"
    return f"{slug}-{index}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


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
    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    generalized_credentials = generalized_analysis.get("generalized_credentials_payload") or []
    if generalized_credentials:
        return "generalized_analysis"
    if extraction_payload.get("field_candidates"):
        return "generalized_analysis"
    return "rule_based"


def _resolve_document_type(extraction_payload: dict[str, Any]) -> str:
    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    summary_payload = generalized_analysis.get("verification_summary_payload") or {}
    summary_document_type = normalize_value(summary_payload.get("document_type"))
    if summary_document_type:
        return summary_document_type
    return str(extraction_payload.get("document_type") or "unknown")


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


def _dedupe_credentials(credentials: list[ExtractedCredential]) -> list[ExtractedCredential]:
    grouped: dict[tuple[str, str, int | None], ExtractedCredential] = {}
    for credential in credentials:
        key = (
            credential.label.lower(),
            (credential.normalized_value or str(credential.value or "")).lower(),
            credential.page,
        )
        current = grouped.get(key)
        if current is None or (credential.confidence or 0) > (current.confidence or 0):
            grouped[key] = credential
    return list(grouped.values())
