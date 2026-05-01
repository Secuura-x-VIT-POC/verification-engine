from __future__ import annotations

from collections import Counter

from .confidence_scorer import compute_extraction_quality
from .cross_field_validator import summarize_credential_validation
from .models import (
    CanonicalSchema,
    CredentialCandidate,
    DocumentMetadata,
    ExtractedField,
    FieldCandidate,
    FieldView,
    GeneralizedAnalysisPayload,
    OCRMetadata,
    ProcessingExtractionResult,
    SafetyReport,
    Sensitivity,
    WorkspaceExtractionView,
)
from .pii_classifier import redact_value


def build_credential_candidates(candidates: list[FieldCandidate], document_type_hint: str) -> list[CredentialCandidate]:
    if not candidates:
        return []

    grouped = [candidate for candidate in candidates if candidate.requires_verification]
    if not grouped:
        grouped = list(candidates)

    issuer = next((candidate.normalized_value for candidate in candidates if candidate.category == "institution"), None)
    subject_name = next((candidate.normalized_value for candidate in candidates if candidate.category == "personal_name"), None)
    issue_date = next((candidate.normalized_value for candidate in candidates if "issue" in candidate.label.lower()), None)
    expiry_date = next((candidate.normalized_value for candidate in candidates if "expiry" in candidate.label.lower()), None)
    confidence = round(sum(candidate.confidence for candidate in grouped) / len(grouped), 4)
    field_ids = [candidate.field_id for candidate in grouped]
    notes, status = summarize_credential_validation(candidates, field_ids)
    return [
        CredentialCandidate(
            credential_id=f"cred_{document_type_hint}_{len(field_ids)}",
            document_type=_map_document_type(document_type_hint),
            issuer=issuer,
            subject_name=subject_name,
            issue_date=issue_date,
            expiry_date=expiry_date,
            field_ids=field_ids,
            confidence=confidence,
            validation_notes=notes,
            validation_status=status,
        )
    ]


def build_processing_result(
    *,
    session_id: str,
    candidates: list[FieldCandidate],
    credential_candidates: list[CredentialCandidate],
    ocr_metadata: OCRMetadata,
    raw_text_per_page: dict[int, str],
    document_type_hint: str,
) -> ProcessingExtractionResult:
    grounded_ratio = (
        sum(1 for candidate in candidates if candidate.bounding_boxes) / len(candidates)
        if candidates
        else 0.0
    )
    extraction_quality = compute_extraction_quality(candidates, grounded_ratio, float(ocr_metadata.avg_confidence or 0.0))
    return ProcessingExtractionResult(
        session_id=session_id,
        field_candidates=candidates,
        credential_candidates=credential_candidates,
        ocr_metadata=ocr_metadata,
        raw_text_per_page=raw_text_per_page,
        page_count=len(raw_text_per_page),
        document_type_hint=document_type_hint,
        extraction_quality=extraction_quality,
    )


def build_workspace_view(processing_result: ProcessingExtractionResult) -> WorkspaceExtractionView:
    field_views = [
        FieldView(
            field_id=candidate.field_id,
            label=candidate.label,
            value_preview=redact_value(candidate.raw_value, candidate.sensitivity),
            category=candidate.category,
            page=candidate.page,
            bounding_boxes=list(candidate.bounding_boxes),
            confidence=candidate.confidence,
            is_pii=candidate.is_pii,
            sensitivity=candidate.sensitivity,
            verification_status=candidate.verification_status,
        )
        for candidate in processing_result.field_candidates
    ]
    credential_summaries = []
    for credential in processing_result.credential_candidates:
        subject_sensitivity = next(
            (
                candidate.sensitivity
                for candidate in processing_result.field_candidates
                if candidate.normalized_value == credential.subject_name
            ),
            None,
        )
        credential_summaries.append(
            {
                "credential_id": credential.credential_id,
                "document_type": credential.document_type,
                "issuer": credential.issuer,
                "subject_name_preview": redact_value(credential.subject_name, subject_sensitivity or Sensitivity.HIGH),
                "issue_date": credential.issue_date,
                "expiry_date": credential.expiry_date,
                "confidence": credential.confidence,
                "validation_notes": credential.validation_notes,
                "validation_status": credential.validation_status,
            }
        )
    return WorkspaceExtractionView(
        session_id=processing_result.session_id,
        field_views=field_views,
        credential_summaries=credential_summaries,
        ocr_metadata=processing_result.ocr_metadata,
        page_count=processing_result.page_count,
        document_type_hint=processing_result.document_type_hint,
        raw_text_persisted=False,
        pii_persisted=False,
        extraction_quality=processing_result.extraction_quality,
    )


def build_canonical_schema(candidates: list[FieldCandidate]) -> CanonicalSchema:
    best_by_key = {}
    mapping = {
        "personal_name": "candidate_name",
        "institution": "institution",
        "credential_title": "credential_type",
        "date": "issue_date",
        "identifier": "document_id",
        "contact": None,
    }
    for candidate in candidates:
        target = mapping.get(candidate.category)
        if target is None:
            if "email" in candidate.label.lower():
                target = "email"
            elif any(token in candidate.label.lower() for token in ("phone", "mobile")):
                target = "phone_number"
            else:
                continue
        current = best_by_key.get(target)
        if current is None or candidate.confidence > current.confidence:
            best_by_key[target] = candidate

    schema = CanonicalSchema()
    for field_name, candidate in best_by_key.items():
        setattr(
            schema,
            field_name,
            ExtractedField(
                value=candidate.raw_value or "",
                confidence=candidate.confidence,
                bounding_boxes=list(candidate.bounding_boxes),
                match_type="grounded" if candidate.bounding_boxes else "ungrounded",
            ),
        )
    return schema


def build_generalized_analysis(processing_result: ProcessingExtractionResult) -> GeneralizedAnalysisPayload:
    profile = {
        "document_family_hints": [processing_result.document_type_hint or "generic"],
        "contains_pii": any(candidate.is_pii for candidate in processing_result.field_candidates),
        "pii_categories": sorted({candidate.category for candidate in processing_result.field_candidates if candidate.is_pii}),
        "likely_sections": [],
        "likely_tables_present": any("table" in candidate.detected_by for candidate in processing_result.field_candidates),
        "likely_form_present": any("layout" in candidate.detected_by for candidate in processing_result.field_candidates),
        "issuer_hints": [candidate.normalized_value for candidate in processing_result.field_candidates if candidate.category == "institution"][:5],
        "structure_notes": [],
    }

    generalized_credentials = []
    for candidate in processing_result.field_candidates:
        box = candidate.bounding_boxes[0].model_dump() if candidate.bounding_boxes else None
        generalized_credentials.append(
            {
                "credential_id": candidate.field_id,
                "label": candidate.label,
                "category": _map_generalized_category(candidate),
                "value": candidate.raw_value,
                "normalized_value": candidate.normalized_value,
                "source_text": candidate.source_text,
                "confidence": candidate.confidence,
                "page": candidate.page,
                "bounding_box": box,
                "is_pii": candidate.is_pii,
                "requires_verification": candidate.requires_verification,
                "verification_reason": f"Verification recommended for {candidate.label}." if candidate.requires_verification else None,
                "extraction_method": candidate.extraction_method,
            }
        )

    counts = Counter(candidate.verification_status for candidate in processing_result.field_candidates)
    summary = {
        "document_type": processing_result.document_type_hint or "generic",
        "total_candidates": len(processing_result.field_candidates),
        "total_credentials": len(processing_result.credential_candidates),
        "total_pii_fields": sum(1 for candidate in processing_result.field_candidates if candidate.is_pii),
        "total_verification_tasks": sum(1 for candidate in processing_result.field_candidates if candidate.requires_verification),
        "highlights_ready": all(bool(candidate.bounding_boxes) for candidate in processing_result.field_candidates if candidate.requires_verification),
        "summary_text": f"Detected {len(processing_result.field_candidates)} field candidates for {processing_result.document_type_hint or 'generic'} document.",
        "green_count": counts.get("GREEN", 0),
        "amber_count": counts.get("AMBER", 0),
        "red_count": counts.get("RED", 0),
        "extraction_quality": processing_result.extraction_quality,
    }
    return GeneralizedAnalysisPayload(
        document_profile_payload=profile,
        generalized_credentials_payload=generalized_credentials,
        verification_summary_payload=summary,
    )


def build_document_metadata(
    *,
    file_name: str,
    file_type: str,
    size_bytes: int,
    processing_result: ProcessingExtractionResult,
    safety_report: SafetyReport,
) -> DocumentMetadata:
    raw_text = "\n".join(processing_result.raw_text_per_page.values())
    return DocumentMetadata(
        file_name=file_name,
        file_type=file_type,
        page_count=processing_result.page_count,
        size_bytes=size_bytes,
        text_char_count=len(raw_text),
        extraction_method=processing_result.ocr_metadata.method_used,
        character_density=round(len("".join(raw_text.split())) / max(processing_result.page_count, 1), 4),
        min_resolution_dpi=safety_report.min_resolution_dpi,
        is_scanned=processing_result.ocr_metadata.ocr_applied,
        sandboxed_processing=safety_report.sandboxed,
    )


def _map_generalized_category(candidate: FieldCandidate) -> str:
    label = candidate.label.lower()
    if candidate.category == "personal_name":
        return "person_name"
    if candidate.category == "institution":
        return "issuer"
    if candidate.category == "credential_title":
        return "credential_title"
    if candidate.category == "score":
        return "score"
    if candidate.category == "date":
        if "birth" in label or label == "dob":
            return "date_of_birth"
        if "issue" in label:
            return "issue_date"
        if "expiry" in label or "valid" in label:
            return "expiry_date"
        return "date_reference"
    if candidate.category == "identifier":
        if "aadhaar" in label:
            return "national_identifier"
        if "pan" in label:
            return "tax_identifier"
        if any(token in label for token in ("roll", "registration", "seat")):
            return "registration_number"
        if "license" in label:
            return "license_number"
        return "document_number"
    if candidate.category == "contact":
        if "email" in label:
            return "email"
        return "phone_number"
    if candidate.category == "address":
        return "address"
    return "other"


def _map_document_type(document_type_hint: str) -> str:
    normalized = (document_type_hint or "generic").lower()
    if normalized in {"academic_degree", "degree"}:
        return "academic_degree"
    if normalized in {"academic_transcript", "transcript", "report_card", "marksheet"}:
        return "academic_transcript"
    if normalized in {"identity_document", "aadhaar_card", "passport", "pan_card"}:
        return "identity_document"
    if normalized in {"certificate"}:
        return "certificate"
    if normalized in {"invoice"}:
        return "invoice"
    if normalized in {"license"}:
        return "license"
    if normalized in {"employment_letter"}:
        return "employment_letter"
    if normalized in {"financial_document"}:
        return "financial_document"
    return "generic"
