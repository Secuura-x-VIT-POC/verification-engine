from __future__ import annotations

import re

from .models import FieldCandidate, Sensitivity, VerificationStatus


HIGH_PII_CATEGORIES = {"personal_name", "identifier"}
MEDIUM_PII_CATEGORIES = {"address", "contact"}


def classify_pii(candidate: FieldCandidate) -> FieldCandidate:
    category = candidate.category
    label = candidate.label.lower()
    explicit_label_pii = any(
        token in label for token in ("address", "email", "phone", "mobile", "aadhaar", "pan", "passport", "roll", "registration")
    )
    name_like_pii = "name" in label and category not in {"institution", "credential_title"}
    is_pii = category in {"personal_name", "identifier", "address", "contact"} or explicit_label_pii or name_like_pii
    if category in HIGH_PII_CATEGORIES:
        sensitivity = Sensitivity.HIGH
    elif category in MEDIUM_PII_CATEGORIES:
        sensitivity = Sensitivity.MEDIUM
    elif is_pii:
        sensitivity = Sensitivity.MEDIUM
    else:
        sensitivity = Sensitivity.LOW
    return candidate.model_copy(update={"is_pii": is_pii, "sensitivity": sensitivity})


def redact_value(value: str | None, sensitivity: Sensitivity) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if sensitivity == Sensitivity.LOW:
        return text
    if len(text) <= 4:
        return "***"
    if sensitivity == Sensitivity.HIGH:
        compact_digits = re.sub(r"\D", "", text)
        if len(compact_digits) >= 6:
            return f"{compact_digits[:2]}***{compact_digits[-2:]}"
        return f"{text[:2]}***{text[-2:]}"
    return f"{text[:1]}***"


def redact_source_snippet(source_text: str | None, raw_value: str | None, sensitivity: Sensitivity) -> str | None:
    if not source_text:
        return None
    snippet = source_text[:120]
    if raw_value and sensitivity != Sensitivity.LOW:
        snippet = snippet.replace(raw_value, redact_value(raw_value, sensitivity))
    return snippet[:120]


def apply_verifier_feedback(candidates: list[FieldCandidate], mismatch_field_ids: list[str]) -> list[FieldCandidate]:
    mismatch_set = set(mismatch_field_ids)
    updated: list[FieldCandidate] = []
    for candidate in candidates:
        if candidate.field_id not in mismatch_set:
            updated.append(candidate.model_copy(deep=True))
            continue
        updated.append(
            candidate.model_copy(
                update={
                    "verification_status": VerificationStatus.RED,
                    "confidence": max(0.0, round(candidate.confidence - 0.25, 4)),
                },
                deep=True,
            )
        )
    return updated
