from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any

from .contracts import BoundingBox, ExtractedCredential


PLANNING_STATUS_VERIFICATION_ELIGIBLE = "verification_eligible"
PLANNING_STATUS_CONTEXT_ONLY = "context_only"
PLANNING_STATUS_METADATA_ONLY = "metadata_only"
PLANNING_STATUS_DISCARD = "discard"

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
        "board",
        "roll number",
        "seat number",
    ),
    "certificate": ("certificate", "certification", "completion", "awarded"),
    "identity": ("identity", "national id", "aadhaar", "date of birth", "dob", "holder"),
}

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
    "phone",
    "email",
)

IDENTIFIER_KEYWORDS = ("id", "identifier", "number", "registration", "roll", "account")

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z .'-]{2,}$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
AADHAAR_PATTERN = re.compile(r"^\d{12}$")
PASSPORT_PATTERN = re.compile(r"^[A-Z][0-9]{6,8}$")
LICENSE_PATTERN = re.compile(r"^[A-Z0-9-]{6,18}$")
ALPHANUMERIC_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{4,24}$")
YEAR_PATTERN = re.compile(r"^(19|20)\d{2}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}[/-]\d{2}[/-]\d{4}$")
PHONE_PATTERN = re.compile(r"^\d{10}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GRADE_PATTERN = re.compile(r"^(?:[A-F][+-]?|(?:\d{1,3}(?:\.\d+)?%?)|(?:\d(?:\.\d+)?/?10))$", re.IGNORECASE)

ACADEMIC_FAMILY_HINTS = (
    "academic",
    "transcript",
    "report_card",
    "report card",
    "marksheet",
    "mark_sheet",
    "mark sheet",
    "grade_report",
    "grade report",
    "certificate",
)
IDENTITY_FAMILY_HINTS = ("identity", "aadhaar", "passport", "license", "licence")
TAX_FAMILY_HINTS = ("tax", "pan")
FINANCIAL_FAMILY_HINTS = ("financial", "bank", "statement")


@dataclass(frozen=True)
class PlannerEntry:
    source_id: str
    key: str
    label: str
    raw_value: Any
    normalized_value: str | None
    source_text: str | None
    confidence: float | None
    page: int | None
    bounding_box: BoundingBox | None
    source_category: str | None
    extraction_method: str
    explicit_requires_verification: bool | None
    explicit_verification_reason: str | None
    explicit_is_pii: bool | None
    semantic_key: str
    data_type: str | None = None
    verification_intent: str | None = None
    importance: str | None = None


@dataclass(frozen=True)
class PlanningDecision:
    planning_status: str
    promoted_label: str
    category: str
    requires_verification: bool
    verification_recommended: bool
    eligibility_reason: str
    grouping_reason: str | None = None


def build_extracted_credentials(extraction_payload: dict[str, Any] | None) -> list[ExtractedCredential]:
    credentials, _context_fields = build_planned_credentials(extraction_payload)
    return credentials


def build_planned_credentials(
    extraction_payload: dict[str, Any] | None,
) -> tuple[list[ExtractedCredential], list[ExtractedCredential]]:
    if not extraction_payload:
        return [], []

    document_type = _resolve_document_type(extraction_payload)
    document_family = _resolve_document_family(extraction_payload)
    extraction_method = _resolve_extraction_method(extraction_payload)

    entries = _build_planner_entries(
        extraction_payload,
        document_type=document_type,
        document_family=document_family,
        extraction_method=extraction_method,
    )
    if not entries:
        return [], []

    support_context = _build_support_context(entries, document_family=document_family)
    credentials: list[ExtractedCredential] = []
    context_fields: list[ExtractedCredential] = []

    for index, entry in enumerate(entries, start=1):
        decision = _determine_planning_decision(
            entry,
            document_type=document_type,
            document_family=document_family,
            support_context=support_context,
        )
        if decision.planning_status == PLANNING_STATUS_DISCARD:
            continue

        credential = _build_credential(
            entry,
            decision,
            credential_id=entry.source_id or _build_credential_id(entry.key, index),
        )
        if decision.planning_status == PLANNING_STATUS_VERIFICATION_ELIGIBLE:
            credentials.append(credential)
        else:
            context_fields.append(credential)

    return _dedupe_credentials(credentials), _dedupe_credentials(context_fields)


def classify_credential_category(
    *,
    label: str,
    key: str | None = None,
    source_category: str | None = None,
    normalized_value: str | None = None,
    document_type: str | None = None,
    semantic_key: str | None = None,
) -> str:
    document_context = (document_type or "").replace("_", " ").lower()
    normalized_source_category = (source_category or "").strip().lower()
    normalized_semantic_key = (semantic_key or "").strip().lower()
    semantic_or_source = normalized_semantic_key or normalized_source_category

    if semantic_or_source in {"full_name", "date_of_birth", "aadhaar_number", "phone_number", "email"}:
        return "identity"
    if semantic_or_source == "address":
        return "address"
    if semantic_or_source == "passport_number":
        return "passport"
    if semantic_or_source == "license_number":
        return "license"
    if semantic_or_source == "pan_number":
        return "tax"
    if semantic_or_source in {
        "student_name",
        "roll_number",
        "seat_number",
        "institution_name",
        "board_name",
        "exam_year",
        "marks",
        "grade",
        "result_status",
    }:
        return "academic"
    if semantic_or_source == "document_number":
        if any(token in document_context for token in ("passport", "travel")):
            return "passport"
        if any(token in document_context for token in ("license", "licence")):
            return "license"
        if any(token in document_context for token in ("tax", "pan")):
            return "tax"
        if any(token in document_context for token in ACADEMIC_FAMILY_HINTS):
            return "academic"
        return "identity"

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

    if any(token in document_context for token in ACADEMIC_FAMILY_HINTS) and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "academic"
    if any(token in document_context for token in ("identity", "personal")) and _contains_any_keyword(primary_haystack, IDENTIFIER_KEYWORDS):
        return "identity"
    return "unknown"


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


def _build_planner_entries(
    extraction_payload: dict[str, Any],
    *,
    document_type: str,
    document_family: str,
    extraction_method: str,
) -> list[PlannerEntry]:
    entries: list[PlannerEntry] = []
    for index, entry in enumerate(_iter_generalized_entries(extraction_payload), start=1):
        raw_value = entry["value"]
        normalized_value = normalize_value(entry.get("normalized_value") or raw_value)
        source_text = _coerce_source_text(entry["source_text"], raw_value)
        if not normalized_value and not source_text:
            continue

        bounding_box = _normalize_bounding_box(entry["bounding_box"])
        page = _coerce_int(entry.get("page"))
        if page is None and bounding_box is not None:
            page = bounding_box.page

        label = normalize_value(entry["label"]) or f"Credential {index}"
        key = str(entry["key"] or _slug(label) or f"candidate_{index}")
        semantic_key = _infer_semantic_key(
            label=label,
            key=key,
            source_category=entry.get("source_category"),
            normalized_value=normalized_value,
            document_type=document_type,
            document_family=document_family,
        )
        entries.append(
            PlannerEntry(
                source_id=str(entry.get("credential_id") or _build_credential_id(key, index)),
                key=key,
                label=label,
                raw_value=raw_value,
                normalized_value=normalized_value,
                source_text=source_text,
                confidence=_coerce_confidence(entry.get("confidence")),
                page=page,
                bounding_box=bounding_box,
                source_category=normalize_value(entry.get("source_category")),
                extraction_method=str(entry.get("extraction_method") or extraction_method),
                explicit_requires_verification=(
                    bool(entry["requires_verification"])
                    if entry.get("requires_verification") is not None
                    else None
                ),
                explicit_verification_reason=normalize_value(entry.get("verification_reason")),
                explicit_is_pii=(
                    bool(entry["is_pii"])
                    if entry.get("is_pii") is not None
                    else None
                ),
                semantic_key=semantic_key,
                data_type=normalize_value(entry.get("data_type") or entry.get("source_category")),
                verification_intent=normalize_value(entry.get("verification_intent")),
                importance=normalize_value(entry.get("importance")),
            )
        )
    return entries


def _determine_planning_decision(
    entry: PlannerEntry,
    *,
    document_type: str,
    document_family: str,
    support_context: dict[str, Any],
) -> PlanningDecision:
    if not _has_planner_grounding(entry):
        return PlanningDecision(
            planning_status=PLANNING_STATUS_DISCARD,
            promoted_label=entry.label,
            category="unknown",
            requires_verification=False,
            verification_recommended=False,
            eligibility_reason="The extracted field has no usable source text or grounding metadata.",
        )

    if (entry.confidence or 0.0) < 0.55:
        return PlanningDecision(
            planning_status=PLANNING_STATUS_DISCARD,
            promoted_label=entry.label,
            category="unknown",
            requires_verification=False,
            verification_recommended=False,
            eligibility_reason="The extracted field confidence is below the planner minimum threshold.",
        )

    value = entry.normalized_value or ""
    semantic_key = entry.semantic_key
    dynamic_decision = _dynamic_planning_decision(entry)
    if dynamic_decision is not None:
        return dynamic_decision

    if semantic_key == "generic_name":
        if _looks_like_name(value) and _supports_academic_name_promotion(entry, document_family, support_context):
            return _eligible_decision(
                promoted_label="Student Name",
                category="academic",
                reason="A strong name field was promoted because academic support fields were also detected.",
                grouping_reason="Grouped with academic anchors such as roll number, institution, board, or marks.",
            )
        if _looks_like_name(value) and _supports_identity_name_promotion(entry, document_family, support_context):
            return _eligible_decision(
                promoted_label="Full Name",
                category="identity",
                reason="A strong name field was promoted because identity-grade supporting fields were also detected.",
                grouping_reason="Grouped with identity anchors such as date of birth or government identifier.",
            )
        return _context_decision(
            promoted_label="Name",
            category="identity",
            reason="Generic name fragments are retained as context until identity or academic support fields make them verification-grade.",
        )

    if semantic_key == "full_name":
        if _looks_like_name(value) and _passes_name_quality(entry):
            return _eligible_decision(
                promoted_label="Full Name",
                category="identity",
                reason="This field is explicitly labeled as a full/holder/applicant name and has a strong multi-token value.",
                grouping_reason=(
                    "Identity anchors were also present."
                    if _supports_identity_name_promotion(entry, document_family, support_context)
                    else None
                ),
            )
        return _context_decision(
            promoted_label="Full Name",
            category="identity",
            reason="The extracted name did not meet minimum quality thresholds for verification.",
        )

    if semantic_key == "student_name":
        if _looks_like_name(value) and _supports_academic_name_promotion(entry, document_family, support_context):
            return _eligible_decision(
                promoted_label="Student Name",
                category="academic",
                reason="This field is explicitly student-scoped and academic support fields are present.",
                grouping_reason="Grouped with academic anchors such as roll number, institution, board, or marks.",
            )
        return _context_decision(
            promoted_label="Student Name",
            category="academic",
            reason="Student name is kept as context until stronger academic support fields are present.",
        )

    if semantic_key == "date_of_birth":
        if _passes_date_quality(entry):
            return _eligible_decision(
                promoted_label="Date of Birth",
                category="identity",
                reason="Date of birth is an inherently verifiable identity field with a normalized date value.",
            )
        return _metadata_decision(
            promoted_label="Date of Birth",
            category="identity",
            reason="The date-of-birth candidate exists but did not meet planner quality thresholds.",
        )

    if semantic_key == "aadhaar_number":
        if _passes_identifier_quality(entry, expected="aadhaar"):
            return _eligible_decision(
                promoted_label="Aadhaar Number",
                category="identity",
                reason="Aadhaar number matched a strong identifier pattern and is treated as a verification-grade identity claim.",
            )
        return _context_decision(
            promoted_label="Aadhaar Number",
            category="identity",
            reason="The Aadhaar-like identifier was detected but did not meet planner quality thresholds.",
        )

    if semantic_key == "pan_number":
        if _passes_identifier_quality(entry, expected="pan"):
            return _eligible_decision(
                promoted_label="PAN Number",
                category="tax",
                reason="PAN number matched a strong tax-identifier pattern and is treated as verification-grade.",
            )
        return _context_decision(
            promoted_label="PAN Number",
            category="tax",
            reason="The PAN-like identifier was detected but did not meet planner quality thresholds.",
        )

    if semantic_key in {"passport_number", "license_number"}:
        expected = "passport" if semantic_key == "passport_number" else "license"
        category = "passport" if semantic_key == "passport_number" else "license"
        promoted_label = "Passport Number" if semantic_key == "passport_number" else "License Number"
        if _passes_identifier_quality(entry, expected=expected):
            return _eligible_decision(
                promoted_label=promoted_label,
                category=category,
                reason="The document number matches a strong document-specific identifier pattern.",
            )
        return _context_decision(
            promoted_label=promoted_label,
            category=category,
            reason="The detected document number did not meet document-specific quality thresholds.",
        )

    if semantic_key in {"roll_number", "seat_number"}:
        promoted_label = "Roll Number" if semantic_key == "roll_number" else "Seat Number"
        if _passes_identifier_quality(entry, expected="academic_id") and _supports_academic_record(document_family, support_context):
            return _eligible_decision(
                promoted_label=promoted_label,
                category="academic",
                reason="Academic identifier fields are verification-grade when they are strong and the document context is academic.",
                grouping_reason="Grouped with academic context such as student name, institution, board, or results.",
            )
        return _context_decision(
            promoted_label=promoted_label,
            category="academic",
            reason="Academic identifiers stay as context until the document is clearly academic and the value is strong.",
        )

    if semantic_key in {"institution_name", "board_name"}:
        promoted_label = "Institution Name" if semantic_key == "institution_name" else "Board Name"
        if _passes_institution_quality(entry) and _supports_academic_record(document_family, support_context):
            return _eligible_decision(
                promoted_label=promoted_label,
                category="academic",
                reason="Issuer-like academic fields are promoted only when the surrounding academic record context is strong.",
                grouping_reason="Grouped with student/roll/result anchors instead of promoted as a standalone issuer fragment.",
            )
        return _context_decision(
            promoted_label=promoted_label,
            category="academic",
            reason="Issuer-like fields are retained as academic context until student/result anchors justify promotion.",
        )

    if semantic_key == "document_number":
        if _passes_identifier_quality(entry, expected="generic_document") and _supports_document_identifier(entry, document_family, support_context):
            category = classify_credential_category(
                label=entry.label,
                key=entry.key,
                source_category=entry.source_category,
                normalized_value=value,
                document_type=document_type,
                semantic_key="document_number",
            )
            return _eligible_decision(
                promoted_label="Document Number",
                category=category,
                reason="Document number was promoted only because the identifier is strong and the document context supports verification.",
                grouping_reason="Grouped with document context such as identity anchors or issuer/date support.",
            )
        return _metadata_decision(
            promoted_label="Document Number",
            category="unknown",
            reason="Generic document numbers are retained as metadata unless document context makes them verification-grade.",
        )

    if semantic_key == "phone_number":
        if _passes_phone_quality(entry):
            return _eligible_decision(
                promoted_label="Phone Number",
                category="identity",
                reason="Phone number is explicit and normalized to a usable mobile number.",
            )
        return _context_decision(
            promoted_label="Phone Number",
            category="identity",
            reason="Phone-like text was detected but did not meet quality thresholds.",
        )

    if semantic_key == "email":
        if _passes_email_quality(entry):
            return _eligible_decision(
                promoted_label="Email",
                category="identity",
                reason="Email is explicit, normalized, and suitable for verification workflows.",
            )
        return _context_decision(
            promoted_label="Email",
            category="identity",
            reason="Email-like text was detected but did not meet planner quality thresholds.",
        )

    if semantic_key == "address":
        if _passes_address_quality(entry):
            return _eligible_decision(
                promoted_label="Address",
                category="address",
                reason="Address is explicit and sufficiently grounded to remain a verification-grade address claim.",
            )
        return _context_decision(
            promoted_label="Address",
            category="address",
            reason="Address text is retained as context because it is too weak or incomplete for deterministic verification.",
        )

    if semantic_key in {"marks", "grade", "result_status", "exam_year"}:
        if _supports_academic_record(document_family, support_context) and _passes_academic_metric_quality(entry, semantic_key):
            return _eligible_decision(
                promoted_label=_display_label_for_semantic_key(semantic_key),
                category="academic",
                reason="Academic result fields are promoted only when the document context is clearly academic and the value is structured enough.",
            )
        return _metadata_decision(
            promoted_label=_display_label_for_semantic_key(semantic_key),
            category="academic",
            reason="Academic metric fields remain metadata until the surrounding academic record context is strong enough.",
        )

    if semantic_key in {"issue_date", "expiry_date", "date_reference"}:
        return _metadata_decision(
            promoted_label=_display_label_for_semantic_key(semantic_key),
            category="unknown",
            reason="Date fields are retained as metadata in this step; they do not become standalone verification tasks by default.",
        )

    if semantic_key in {"credential_title", "program_name", "program_branch", "issuer", "registration_number"}:
        return _context_decision(
            promoted_label=_display_label_for_semantic_key(semantic_key),
            category=classify_credential_category(
                label=entry.label,
                key=entry.key,
                source_category=entry.source_category,
                normalized_value=value,
                document_type=document_type,
                semantic_key=semantic_key,
            ),
            reason="This field is useful context for grouping and evidence, but not a standalone verification credential by default.",
        )

    fallback_category = classify_credential_category(
        label=entry.label,
        key=entry.key,
        source_category=entry.source_category,
        normalized_value=value,
        document_type=document_type,
        semantic_key=semantic_key,
    )
    return PlanningDecision(
        planning_status=PLANNING_STATUS_DISCARD,
        promoted_label=entry.label,
        category=fallback_category,
        requires_verification=False,
        verification_recommended=False,
        eligibility_reason="The field does not map to a bounded verification-grade semantic rule in the current planner.",
    )


def _build_credential(
    entry: PlannerEntry,
    decision: PlanningDecision,
    *,
    credential_id: str,
) -> ExtractedCredential:
    category = decision.category
    normalized_value = normalize_value(entry.normalized_value or entry.raw_value)
    is_pii = (
        bool(entry.explicit_is_pii)
        if entry.explicit_is_pii is not None
        else is_pii_field(
            label=decision.promoted_label,
            key=entry.key,
            category=category,
            normalized_value=normalized_value,
        )
    )
    verification_reason = (
        decision.eligibility_reason
        if decision.requires_verification
        else entry.explicit_verification_reason or decision.eligibility_reason
    )
    return ExtractedCredential(
        credential_id=credential_id,
        label=decision.promoted_label,
        category=category,
        value=entry.raw_value,
        normalized_value=normalized_value,
        source_text=entry.source_text,
        confidence=entry.confidence,
        page=entry.page,
        bounding_box=entry.bounding_box,
        is_pii=is_pii,
        requires_verification=decision.requires_verification,
        verification_recommended=decision.verification_recommended,
        verification_reason=verification_reason,
        planning_status=decision.planning_status,
        eligibility_reason=decision.eligibility_reason,
        grouping_reason=decision.grouping_reason,
        source_candidate_ids=[entry.source_id],
        extraction_method=entry.extraction_method,
    )


def _build_support_context(entries: list[PlannerEntry], *, document_family: str) -> dict[str, Any]:
    semantic_keys = [entry.semantic_key for entry in entries]
    counts = Counter(semantic_keys)
    return {
        "document_family": document_family,
        "semantic_counts": counts,
        "has_identity_anchor": any(
            key in counts
            for key in ("date_of_birth", "aadhaar_number", "pan_number", "passport_number", "license_number", "document_number")
        ),
        "has_academic_anchor": any(
            key in counts
            for key in ("roll_number", "seat_number", "institution_name", "board_name", "marks", "grade", "result_status", "exam_year", "student_name")
        ),
        "has_document_anchor": any(
            key in counts
            for key in ("document_number", "issue_date", "expiry_date", "institution_name", "board_name", "issuer")
        ),
    }


def _supports_identity_name_promotion(
    entry: PlannerEntry,
    document_family: str,
    support_context: dict[str, Any],
) -> bool:
    lower_label = entry.label.lower()
    return (
        any(token in lower_label for token in ("full name", "holder name", "applicant name"))
        or document_family in {"identity", "passport", "license", "tax"}
        or bool(support_context["has_identity_anchor"])
    )


def _supports_academic_name_promotion(
    entry: PlannerEntry,
    document_family: str,
    support_context: dict[str, Any],
) -> bool:
    lower_label = entry.label.lower()
    return (
        "student" in lower_label
        or document_family == "academic"
        or bool(support_context["has_academic_anchor"])
    )


def _supports_academic_record(document_family: str, support_context: dict[str, Any]) -> bool:
    return document_family == "academic" or bool(support_context["has_academic_anchor"])


def _dynamic_planning_decision(entry: PlannerEntry) -> PlanningDecision | None:
    intent = (entry.verification_intent or "").strip().lower()
    data_type = (entry.data_type or entry.source_category or "").strip().lower()
    importance = (entry.importance or "").strip().lower()
    if not intent and data_type not in {"person_name", "organization", "date", "identifier", "amount", "address", "status", "score", "category", "free_text", "unknown"}:
        return None

    if intent == "identity" and data_type == "person_name":
        return _eligible_decision(promoted_label=entry.label, category="identity", reason="Dynamic claim requests identity verification for a person-name value.")
    if intent == "academic" and data_type in {"identifier", "score", "status", "person_name", "organization"}:
        return _eligible_decision(promoted_label=entry.label, category="academic", reason="Dynamic claim requests academic verification based on data type and intent.")
    if intent == "issuer_authenticity" and data_type == "organization":
        return _eligible_decision(promoted_label=entry.label, category="issuer_authenticity", reason="Dynamic claim requests issuer authenticity verification.")
    if intent == "date_validity" and data_type == "date":
        return _eligible_decision(promoted_label=entry.label, category="date_validity", reason="Dynamic claim requests date validity verification.")
    if intent in {"employment", "financial", "address", "generic_record"}:
        category = "address" if intent == "address" else intent
        return _eligible_decision(promoted_label=entry.label, category=category, reason="Dynamic claim has an explicit verification intent.")
    if intent == "manual_review" or (data_type in {"unknown", "free_text"} and importance in {"critical", "important"}):
        return _context_decision(promoted_label=entry.label, category="manual_review", reason="No executable provider is implied; route this dynamic claim to manual review.")
    return None


def _supports_document_identifier(
    entry: PlannerEntry,
    document_family: str,
    support_context: dict[str, Any],
) -> bool:
    lower_label = entry.label.lower()
    if any(token in lower_label for token in ("passport", "license", "licence", "document number")):
        return True
    if document_family in {"identity", "passport", "license", "tax"}:
        return True
    return bool(support_context["has_identity_anchor"] and support_context["has_document_anchor"])


def _passes_name_quality(entry: PlannerEntry) -> bool:
    return _looks_like_name(entry.normalized_value) and (entry.confidence or 0.0) >= 0.75


def _passes_date_quality(entry: PlannerEntry) -> bool:
    return bool(entry.normalized_value and DATE_PATTERN.match(entry.normalized_value)) and (entry.confidence or 0.0) >= 0.7


def _passes_identifier_quality(entry: PlannerEntry, *, expected: str) -> bool:
    normalized_value = _compact_identifier(entry.normalized_value)
    if not normalized_value or (entry.confidence or 0.0) < 0.72:
        return False
    if expected == "aadhaar":
        return bool(AADHAAR_PATTERN.match(normalized_value))
    if expected == "pan":
        return bool(PAN_PATTERN.match(normalized_value))
    if expected == "passport":
        return bool(PASSPORT_PATTERN.match(normalized_value))
    if expected == "license":
        return bool(LICENSE_PATTERN.match(normalized_value))
    if expected == "academic_id":
        return bool(ALPHANUMERIC_ID_PATTERN.match(normalized_value)) and len(normalized_value) >= 6
    return bool(ALPHANUMERIC_ID_PATTERN.match(normalized_value))


def _passes_phone_quality(entry: PlannerEntry) -> bool:
    return bool(entry.normalized_value and PHONE_PATTERN.match(_digits_only(entry.normalized_value))) and (entry.confidence or 0.0) >= 0.75


def _passes_email_quality(entry: PlannerEntry) -> bool:
    return bool(entry.normalized_value and EMAIL_PATTERN.match(entry.normalized_value)) and (entry.confidence or 0.0) >= 0.75


def _passes_address_quality(entry: PlannerEntry) -> bool:
    value = entry.normalized_value or ""
    return len(value) >= 10 and any(character.isdigit() for character in value) and (entry.confidence or 0.0) >= 0.8


def _passes_institution_quality(entry: PlannerEntry) -> bool:
    value = entry.normalized_value or ""
    collapsed = value.lower().strip()
    if len(collapsed) < 4 or (entry.confidence or 0.0) < 0.75:
        return False
    if collapsed in {"issuer", "institution", "board", "school", "university", "college"}:
        return False
    return any(character.isalpha() for character in collapsed)


def _passes_academic_metric_quality(entry: PlannerEntry, semantic_key: str) -> bool:
    value = (entry.normalized_value or "").strip()
    confidence = entry.confidence or 0.0
    if semantic_key == "exam_year":
        return bool(YEAR_PATTERN.match(value)) and confidence >= 0.72
    if semantic_key == "result_status":
        return value.lower() in {"pass", "passed", "fail", "failed", "distinction", "first class", "second class"} and confidence >= 0.7
    return bool(GRADE_PATTERN.match(value)) and confidence >= 0.68


def _has_planner_grounding(entry: PlannerEntry) -> bool:
    return bool(entry.source_text or entry.bounding_box is not None)


def _looks_like_name(value: str | None) -> bool:
    if not value or not NAME_PATTERN.match(value):
        return False
    return len([part for part in value.split(" ") if part]) >= 2


def _compact_identifier(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def _digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _eligible_decision(
    *,
    promoted_label: str,
    category: str,
    reason: str,
    grouping_reason: str | None = None,
) -> PlanningDecision:
    return PlanningDecision(
        planning_status=PLANNING_STATUS_VERIFICATION_ELIGIBLE,
        promoted_label=promoted_label,
        category=category,
        requires_verification=True,
        verification_recommended=True,
        eligibility_reason=reason,
        grouping_reason=grouping_reason,
    )


def _context_decision(
    *,
    promoted_label: str,
    category: str,
    reason: str,
) -> PlanningDecision:
    return PlanningDecision(
        planning_status=PLANNING_STATUS_CONTEXT_ONLY,
        promoted_label=promoted_label,
        category=category,
        requires_verification=False,
        verification_recommended=False,
        eligibility_reason=reason,
    )


def _metadata_decision(
    *,
    promoted_label: str,
    category: str,
    reason: str,
) -> PlanningDecision:
    return PlanningDecision(
        planning_status=PLANNING_STATUS_METADATA_ONLY,
        promoted_label=promoted_label,
        category=category,
        requires_verification=False,
        verification_recommended=False,
        eligibility_reason=reason,
    )


def _infer_semantic_key(
    *,
    label: str,
    key: str | None,
    source_category: str | None,
    normalized_value: str | None,
    document_type: str,
    document_family: str,
) -> str:
    label_haystack = " ".join(
        part.lower()
        for part in ((label or ""), (key or ""), (source_category or ""))
        if part
    )
    source = (source_category or "").strip().lower()
    compact_value = _compact_identifier(normalized_value)

    if source == "person_name" or "name" in label_haystack:
        if "student" in label_haystack or "name of student" in label_haystack:
            return "student_name"
        if any(token in label_haystack for token in ("full name", "holder name", "applicant name")):
            return "full_name"
        return "generic_name"
    if source == "date_of_birth":
        return "date_of_birth"
    if source == "address":
        return "address"
    if source == "email":
        return "email"
    if source == "phone_number":
        return "phone_number"
    if source == "issuer":
        if "board" in label_haystack:
            return "board_name"
        if any(token in label_haystack for token in ("institution", "university", "college", "school", "institute")) or document_family == "academic":
            return "institution_name"
        return "issuer"
    if source == "credential_title":
        return "credential_title"
    if source == "program_name":
        return "program_name"
    if source == "program_branch":
        return "program_branch"
    if source == "registration_number":
        if "seat" in label_haystack:
            return "seat_number"
        if any(token in label_haystack for token in ("roll", "reg", "registration")) or document_family == "academic":
            return "roll_number"
        return "registration_number"
    if source == "document_number":
        if "passport" in label_haystack or PASSPORT_PATTERN.match(compact_value):
            return "passport_number"
        if any(token in label_haystack for token in ("license", "licence")) or LICENSE_PATTERN.match(compact_value):
            return "license_number"
        return "document_number"
    if source == "license_number":
        return "license_number"
    if source == "tax_identifier":
        if "pan" in label_haystack or PAN_PATTERN.match(compact_value):
            return "pan_number"
        return "tax_identifier"
    if source == "national_identifier":
        if "aadhaar" in label_haystack or AADHAAR_PATTERN.match(_digits_only(normalized_value)):
            return "aadhaar_number"
        return "government_identifier"
    if source == "score":
        if any(token in label_haystack for token in ("marks", "percentage", "cgpa", "gpa", "score")):
            return "marks"
        if "grade" in label_haystack:
            return "grade"
        return "marks"
    if source == "issue_date":
        return "issue_date"
    if source == "expiry_date":
        return "expiry_date"
    if source == "date_reference":
        if "exam year" in label_haystack or label_haystack.endswith(" year"):
            return "exam_year"
        if "result" in label_haystack:
            return "result_status"
        return "date_reference"

    if "aadhaar" in label_haystack or AADHAAR_PATTERN.match(_digits_only(normalized_value)):
        return "aadhaar_number"
    if "pan" in label_haystack or PAN_PATTERN.match(compact_value):
        return "pan_number"
    if "passport" in label_haystack:
        return "passport_number"
    if any(token in label_haystack for token in ("license", "licence")):
        return "license_number"
    if any(token in label_haystack for token in ("roll number", "roll no", "seat number")):
        return "roll_number"
    if "institution" in label_haystack or "university" in label_haystack or "college" in label_haystack:
        return "institution_name"
    if "board" in label_haystack:
        return "board_name"
    if "date of birth" in label_haystack or "dob" in label_haystack:
        return "date_of_birth"
    if "issue date" in label_haystack:
        return "issue_date"
    if "expiry date" in label_haystack:
        return "expiry_date"
    if "phone" in label_haystack or "mobile" in label_haystack:
        return "phone_number"
    if "email" in label_haystack:
        return "email"
    if "address" in label_haystack:
        return "address"
    if "credential" in label_haystack or "degree" in label_haystack:
        return "credential_title"
    if "date" in label_haystack or DATE_PATTERN.match(normalized_value or ""):
        return "date_reference"
    if _contains_any_keyword(label_haystack, IDENTIFIER_KEYWORDS):
        return "document_number"
    return "unknown"


def _display_label_for_semantic_key(semantic_key: str) -> str:
    return {
        "credential_title": "Credential Title",
        "program_name": "Program Name",
        "program_branch": "Program Branch",
        "issuer": "Issuer",
        "registration_number": "Registration Number",
        "issue_date": "Issue Date",
        "expiry_date": "Expiry Date",
        "date_reference": "Date",
        "exam_year": "Exam Year",
        "marks": "Marks",
        "grade": "Grade",
        "result_status": "Result Status",
        "government_identifier": "Government Identifier",
        "tax_identifier": "Tax Identifier",
    }.get(semantic_key, semantic_key.replace("_", " ").title())


def _iter_generalized_entries(extraction_payload: dict[str, Any]) -> list[dict[str, Any]]:
    view = extraction_payload.get("view") if isinstance(extraction_payload.get("view"), dict) else {}
    dynamic_claims = view.get("dynamic_claims") if isinstance(view, dict) else None
    if isinstance(dynamic_claims, list) and dynamic_claims:
        entries = []
        for index, claim in enumerate(dynamic_claims, start=1):
            if not isinstance(claim, dict):
                continue
            label = str(claim.get("label") or f"Claim {index}")
            key = str(claim.get("field_id") or claim.get("claim_id") or _slug(label) or f"claim_{index}")
            entries.append(
                {
                    "credential_id": claim.get("field_id") or claim.get("claim_id"),
                    "key": key,
                    "label": label,
                    "value": claim.get("extracted_value") or claim.get("value"),
                    "normalized_value": claim.get("normalized_value"),
                    "confidence": claim.get("confidence"),
                    "bounding_box": claim.get("bounding_box"),
                    "page": claim.get("page") or claim.get("page_number"),
                    "source_text": None,
                    "extraction_method": claim.get("extraction_method") or "pp_chatocr_v4",
                    "source_category": claim.get("data_type") or claim.get("category"),
                    "data_type": claim.get("data_type"),
                    "verification_intent": claim.get("verification_intent"),
                    "importance": claim.get("importance"),
                    "is_pii": claim.get("is_pii"),
                    "requires_verification": claim.get("requires_verification"),
                    "verification_reason": claim.get("verification_reason") or claim.get("reason"),
                }
            )
        return entries

    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    if not generalized_analysis and isinstance(extraction_payload.get("view"), dict):
        generalized_analysis = (extraction_payload.get("view") or {}).get("generalized_analysis") or {}
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
                    "data_type": credential.get("data_type"),
                    "verification_intent": credential.get("verification_intent"),
                    "importance": credential.get("importance"),
                }
            )
        return entries

    field_candidates = extraction_payload.get("field_candidates")
    if not field_candidates and isinstance(extraction_payload.get("view"), dict):
        field_candidates = (extraction_payload.get("view") or {}).get("field_candidates")
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
                    "data_type": candidate.get("data_type"),
                    "verification_intent": candidate.get("verification_intent"),
                    "importance": candidate.get("importance"),
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
    if not generalized_analysis and isinstance(extraction_payload.get("view"), dict):
        generalized_analysis = (extraction_payload.get("view") or {}).get("generalized_analysis") or {}
    summary_payload = generalized_analysis.get("verification_summary_payload") or {}
    summary_document_type = normalize_value(summary_payload.get("document_type"))
    if summary_document_type:
        return summary_document_type
    if extraction_payload.get("document_type"):
        return str(extraction_payload.get("document_type"))
    if isinstance(extraction_payload.get("view"), dict):
        return str((extraction_payload.get("view") or {}).get("document_type") or "unknown")
    return "unknown"


def _resolve_document_family(extraction_payload: dict[str, Any]) -> str:
    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    profile_payload = generalized_analysis.get("document_profile_payload") or {}
    family_hints = list(profile_payload.get("document_family_hints") or [])
    candidates = family_hints + [_resolve_document_type(extraction_payload)]
    for candidate in candidates:
        normalized = str(candidate or "").replace("_", " ").lower()
        if any(token in normalized for token in ACADEMIC_FAMILY_HINTS):
            return "academic"
        if any(token in normalized for token in TAX_FAMILY_HINTS):
            return "tax"
        if "passport" in normalized:
            return "passport"
        if "license" in normalized or "licence" in normalized:
            return "license"
        if any(token in normalized for token in IDENTITY_FAMILY_HINTS):
            return "identity"
        if any(token in normalized for token in FINANCIAL_FAMILY_HINTS):
            return "financial"
    return "generic"


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
    grouped: dict[tuple[str, str, int | None, str], ExtractedCredential] = {}
    for credential in credentials:
        key = (
            credential.label.lower(),
            (credential.normalized_value or str(credential.value or "")).lower(),
            credential.page,
            credential.planning_status,
        )
        current = grouped.get(key)
        if current is None or (credential.confidence or 0) > (current.confidence or 0):
            grouped[key] = credential
    return list(grouped.values())
