from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import re
from typing import Iterable, List, Sequence

from extraction.grounding.spatial_locator import MIN_ACCEPTED_CONFIDENCE, ground_value_to_spatial_map
from extraction.analysis.nvidia_enrichment import enrich_field_candidates_with_nvidia
from extraction.schema.models import (
    BoundingBox,
    CredentialAudit,
    DocumentProfile,
    EnrichmentMetadata,
    EvidenceLine,
    ExtractedCredential,
    ExtractionWarning,
    FieldCandidate,
    GeneralizedAnalysisPayload,
    PageStructureProfile,
    SpatialTextToken,
    VerificationPlanItem,
    VerificationSummary,
)

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b|\b\d{4}-\d{4}\b", re.IGNORECASE)
ID_PATTERN = re.compile(r"\b[A-Z]{2,5}\d{5,16}\b")
PERCENT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?%|\bCGPA\s*[-:]?\s*\d+(?:\.\d+)?/?10\b", re.IGNORECASE)
GOV_ID_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b")

LABEL_CONFIG = {
    "name": ("person_name", True, "identity_registry"),
    "candidate name": ("person_name", True, "identity_registry"),
    "full name": ("person_name", True, "identity_registry"),
    "student name": ("person_name", True, "identity_registry"),
    "holder name": ("person_name", True, "identity_registry"),
    "name of student": ("person_name", True, "identity_registry"),
    "institution": ("issuer", False, "institution_registry"),
    "issuer": ("issuer", False, "institution_registry"),
    "university": ("issuer", False, "institution_registry"),
    "board": ("issuer", False, "institution_registry"),
    "school": ("issuer", False, "institution_registry"),
    "degree": ("credential_title", False, "credential_registry"),
    "credential": ("credential_title", False, "credential_registry"),
    "certificate": ("credential_title", False, "credential_registry"),
    "course": ("program_name", False, "institution_registry"),
    "branch": ("program_branch", False, "institution_registry"),
    "score": ("score", False, "records_registry"),
    "cgpa": ("score", False, "records_registry"),
    "grade": ("score", False, "records_registry"),
    "marks": ("score", False, "records_registry"),
    "percentage": ("score", False, "records_registry"),
    "dob": ("date_of_birth", True, "identity_registry"),
    "date of birth": ("date_of_birth", True, "identity_registry"),
    "birth date": ("date_of_birth", True, "identity_registry"),
    "year of birth": ("date_of_birth", True, "identity_registry"),
    "issue date": ("issue_date", False, "issuer_portal"),
    "expiry date": ("expiry_date", False, "issuer_portal"),
    "registration number": ("registration_number", False, "records_registry"),
    "roll number": ("registration_number", False, "records_registry"),
    "roll no": ("registration_number", False, "records_registry"),
    "document number": ("document_number", False, "issuer_portal"),
    "license number": ("license_number", False, "issuer_portal"),
    "email": ("email", True, "identity_registry"),
    "phone": ("phone_number", True, "identity_registry"),
    "mobile": ("phone_number", True, "identity_registry"),
    "address": ("address", True, "identity_registry"),
    "pan": ("tax_identifier", True, "government_registry"),
    "aadhaar": ("national_identifier", True, "government_registry"),
    "year": ("date_reference", False, "records_registry"),
}

CANONICAL_LABELS = {
    "person_name": "name",
    "issuer": "issuer",
    "credential_title": "credential_title",
    "program_name": "program_name",
    "program_branch": "program_branch",
    "score": "score",
    "date_of_birth": "date_of_birth",
    "issue_date": "issue_date",
    "expiry_date": "expiry_date",
    "registration_number": "registration_number",
    "document_number": "document_id",
    "license_number": "license_number",
    "email": "email",
    "phone_number": "phone_number",
    "address": "address",
    "tax_identifier": "tax_identifier",
    "national_identifier": "national_identifier",
    "date_reference": "date",
}


def build_generalized_analysis(
    raw_text: str,
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    warnings: List[ExtractionWarning],
) -> tuple[List[EvidenceLine], List[FieldCandidate], GeneralizedAnalysisPayload, EnrichmentMetadata]:
    evidence_lines = build_evidence_lines(spatial_text_map)
    field_candidates = extract_field_candidates(raw_text, evidence_lines, spatial_text_map, extraction_method, warnings)
    field_candidates, enrichment_metadata = enrich_field_candidates_with_nvidia(
        raw_text=raw_text,
        evidence_lines=evidence_lines,
        spatial_text_map=spatial_text_map,
        extraction_method=extraction_method,
        warnings=warnings,
        base_candidates=field_candidates,
    )
    document_profile = build_document_profile(raw_text, evidence_lines, extraction_method)
    credentials = build_credentials(field_candidates)
    verification_plan = build_verification_plan(credentials, document_profile)
    audits = build_credential_audits(credentials)
    summary = build_verification_summary(document_profile, field_candidates, credentials, verification_plan)
    payload = GeneralizedAnalysisPayload(
        document_profile_payload=document_profile,
        generalized_credentials_payload=credentials,
        verification_plan_payload=verification_plan,
        credential_audits_payload=audits,
        verification_summary_payload=summary,
        generalized_analysis_status="completed",
    )
    return evidence_lines, field_candidates, payload, enrichment_metadata


def build_evidence_lines(spatial_text_map: Sequence[SpatialTextToken]) -> List[EvidenceLine]:
    lines: List[EvidenceLine] = []
    by_page: dict[int, list[tuple[int, SpatialTextToken]]] = defaultdict(list)
    for index, token in enumerate(spatial_text_map):
        by_page[token.page].append((index, token))

    for page, indexed_tokens in by_page.items():
        indexed_tokens.sort(key=lambda item: (round(item[1].bbox[1], 1), item[1].bbox[0]))
        current_tokens: list[SpatialTextToken] = []
        current_indices: list[int] = []
        current_y: float | None = None
        for index, token in indexed_tokens:
            token_y = token.bbox[1]
            if current_y is None or abs(token_y - current_y) <= 4.0:
                current_tokens.append(token)
                current_indices.append(index)
                current_y = token_y if current_y is None else min(current_y, token_y)
                continue
            lines.append(_tokens_to_line(page, current_tokens, current_indices))
            current_tokens = [token]
            current_indices = [index]
            current_y = token_y
        if current_tokens:
            lines.append(_tokens_to_line(page, current_tokens, current_indices))
    return lines


def extract_field_candidates(
    raw_text: str,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    warnings: List[ExtractionWarning],
) -> List[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    seen: set[tuple[str, str, int]] = set()

    for line in evidence_lines:
        candidates.extend(_extract_label_candidates(line, spatial_text_map, extraction_method, seen))

    candidates.extend(_extract_pattern_candidates(raw_text, evidence_lines, spatial_text_map, extraction_method, seen))
    candidates = [candidate for candidate in candidates if candidate.confidence >= MIN_ACCEPTED_CONFIDENCE]
    candidates = _dedupe_candidates(candidates)
    if not candidates and raw_text.strip():
        warnings.append(
            ExtractionWarning(
                code="NO_GROUNDED_FIELD_CANDIDATES",
                message="The parser found text but could not ground any field candidates confidently.",
            )
        )
    return candidates


def build_document_profile(raw_text: str, evidence_lines: Sequence[EvidenceLine], extraction_method: str) -> DocumentProfile:
    sections = _detect_sections(evidence_lines)
    family_hints = _document_family_hints(raw_text)
    pii_categories = _detect_pii_categories(raw_text)
    page_profiles = _build_page_profiles(evidence_lines, extraction_method)
    return DocumentProfile(
        document_family_hints=family_hints,
        contains_pii=bool(pii_categories),
        pii_categories=pii_categories,
        likely_sections=sections,
        likely_tables_present=any(profile.likely_table for profile in page_profiles),
        likely_form_present=any(profile.likely_form for profile in page_profiles),
        issuer_hints=_issuer_hints(evidence_lines),
        structure_notes=_structure_notes(family_hints, sections, page_profiles),
        page_profiles=page_profiles,
    )


def build_credentials(field_candidates: Sequence[FieldCandidate]) -> List[ExtractedCredential]:
    credentials = []
    for candidate in field_candidates:
        credentials.append(
            ExtractedCredential(
                credential_id=f"cred_{hashlib.sha1(candidate.candidate_id.encode('utf-8')).hexdigest()[:10]}",
                label=candidate.label,
                category=candidate.category,
                value=candidate.raw_value,
                normalized_value=candidate.normalized_value,
                source_text=candidate.source_text,
                confidence=candidate.confidence,
                page=candidate.page,
                bounding_box=candidate.bounding_box,
                is_pii=candidate.is_pii,
                requires_verification=candidate.requires_verification,
                verification_reason=candidate.verification_reason,
                extraction_method=candidate.extraction_method,
                candidate_ids=[candidate.candidate_id],
            )
        )
    return _dedupe_credentials(credentials)


def build_verification_plan(credentials: Sequence[ExtractedCredential], document_profile: DocumentProfile) -> List[VerificationPlanItem]:
    items = []
    for index, credential in enumerate(credentials, start=1):
        items.append(
            VerificationPlanItem(
                plan_item_id=f"plan_{index:03d}",
                credential_id=credential.credential_id,
                verifier_key=_suggest_verifier_key(credential.category, document_profile.document_family_hints),
                verifier_type="deterministic_lookup",
                priority="high" if credential.requires_verification and not credential.is_pii else "medium",
                reason=credential.verification_reason or f"Verify {credential.label}.",
            )
        )
    return items


def build_credential_audits(credentials: Sequence[ExtractedCredential]) -> List[CredentialAudit]:
    return [
        CredentialAudit(
            audit_id=f"audit_{index:03d}",
            credential_id=credential.credential_id,
            label=credential.label,
            status="extracted",
            confidence=credential.confidence,
            evidence=credential.source_text,
            page=credential.page,
            bounding_box=credential.bounding_box,
            explanation=f"{credential.label} was extracted and grounded from the document.",
            source_provenance=f"page {credential.page} / method={credential.extraction_method}",
        )
        for index, credential in enumerate(credentials, start=1)
    ]


def build_verification_summary(
    document_profile: DocumentProfile,
    field_candidates: Sequence[FieldCandidate],
    credentials: Sequence[ExtractedCredential],
    verification_plan: Sequence[VerificationPlanItem],
) -> VerificationSummary:
    document_type = document_profile.document_family_hints[0] if document_profile.document_family_hints else "generic_pdf_evidence"
    pii_count = sum(1 for candidate in field_candidates if candidate.is_pii)
    return VerificationSummary(
        document_type=document_type,
        total_candidates=len(field_candidates),
        total_credentials=len(credentials),
        total_pii_fields=pii_count,
        total_verification_tasks=len(verification_plan),
        highlights_ready=all(credential.bounding_box is not None for credential in credentials),
        summary_text=(
            f"Detected {len(credentials)} grounded credential claims from a {document_type} document. "
            f"PII fields detected: {pii_count}. Verification tasks prepared: {len(verification_plan)}."
        ),
    )


def _extract_label_candidates(
    line: EvidenceLine,
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    seen: set[tuple[str, str, int]],
) -> list[FieldCandidate]:
    matches = re.findall(r"([A-Za-z][A-Za-z /&().-]{1,60})\s*[:\-]\s*(.+)", line.text)
    output = []
    for label_text, value_text in matches:
        config = _resolve_label_config(label_text)
        if config is None:
            continue
        category, is_pii, verifier_key = config
        normalized_value = _normalize_value(value_text, category)
        key = (_canonical_label(category), normalized_value, line.page)
        if key in seen:
            continue
        boxes, confidence, match_type = ground_value_to_spatial_map(value_text.strip(), spatial_text_map)
        if confidence < MIN_ACCEPTED_CONFIDENCE:
            continue
        seen.add(key)
        output.append(
            FieldCandidate(
                candidate_id=_candidate_id(label_text, value_text, line.page),
                label=CANONICAL_LABELS.get(category, _slug(label_text)),
                category=category,
                raw_value=value_text.strip(),
                normalized_value=normalized_value,
                source_text=line.text,
                evidence_snippet=line.text,
                page=line.page,
                bounding_box=boxes[0] if boxes else line.bbox,
                confidence=confidence,
                grounding_match_type=match_type,
                is_pii=is_pii,
                requires_verification=True,
                verification_reason=f"{label_text.strip()} should be checked via {verifier_key}.",
                extraction_method=extraction_method,
                source=line.source,
            )
        )
    return output


def _extract_pattern_candidates(
    raw_text: str,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    seen: set[tuple[str, str, int]],
) -> list[FieldCandidate]:
    specs = [
        ("email", "email", EMAIL_PATTERN, True, "identity_registry"),
        ("phone_number", "phone_number", PHONE_PATTERN, True, "identity_registry"),
        ("document_id", "document_number", ID_PATTERN, False, "issuer_portal"),
        ("date", "date_reference", DATE_PATTERN, False, "issuer_portal"),
        ("score", "score", PERCENT_PATTERN, False, "records_registry"),
        ("government_identifier", "national_identifier", GOV_ID_PATTERN, True, "government_registry"),
    ]
    output = []
    for label, category, pattern, is_pii, verifier_key in specs:
        for match in pattern.finditer(raw_text):
            value = match.group(0).strip()
            page, snippet = _find_evidence_for_value(value, evidence_lines)
            key = (label, _normalize_value(value, category), page)
            if key in seen:
                continue
            boxes, confidence, match_type = ground_value_to_spatial_map(value, spatial_text_map)
            if confidence < MIN_ACCEPTED_CONFIDENCE:
                continue
            seen.add(key)
            output.append(
                FieldCandidate(
                    candidate_id=_candidate_id(label, value, page),
                    label=label,
                    category=category,
                    raw_value=value,
                    normalized_value=_normalize_value(value, category),
                    source_text=snippet,
                    evidence_snippet=snippet,
                    page=page,
                    bounding_box=boxes[0] if boxes else None,
                    confidence=confidence,
                    grounding_match_type=match_type,
                    is_pii=is_pii,
                    requires_verification=True,
                    verification_reason=f"{label} should be checked via {verifier_key}.",
                    extraction_method=extraction_method,
                )
            )
    return output


def _tokens_to_line(page: int, tokens: Sequence[SpatialTextToken], token_indices: Sequence[int]) -> EvidenceLine:
    return EvidenceLine(
        page=page,
        text=" ".join(token.text for token in tokens).strip(),
        bbox=BoundingBox(
            page=page,
            x0=round(min(token.bbox[0] for token in tokens), 2),
            y0=round(min(token.bbox[1] for token in tokens), 2),
            x1=round(max(token.bbox[2] for token in tokens), 2),
            y1=round(max(token.bbox[3] for token in tokens), 2),
        ),
        token_indices=list(token_indices),
        source=tokens[0].source if tokens else "native_text",
    )


def _build_page_profiles(evidence_lines: Sequence[EvidenceLine], extraction_method: str) -> List[PageStructureProfile]:
    by_page: dict[int, list[EvidenceLine]] = defaultdict(list)
    for line in evidence_lines:
        by_page[line.page].append(line)
    profiles = []
    for page, lines in sorted(by_page.items()):
        profiles.append(
            PageStructureProfile(
                page=page,
                extraction_method=extraction_method,
                word_count=sum(len(line.text.split()) for line in lines),
                character_density=round(sum(len(line.text) for line in lines) / max(len(lines), 1), 4),
                section_headers=[line.text for line in lines if _is_section_header(line.text)][:10],
                likely_table=any(_looks_like_table_row(line.text) for line in lines),
                likely_form=any(":" in line.text and len(line.text.split(":", 1)[0].split()) <= 4 for line in lines),
            )
        )
    return profiles


def _detect_sections(evidence_lines: Sequence[EvidenceLine]) -> List[str]:
    sections = []
    for line in evidence_lines:
        normalized = line.text.lower().strip().strip(":")
        if normalized and _is_section_header(line.text) and normalized not in sections:
            sections.append(normalized)
    return sections


def _document_family_hints(raw_text: str) -> List[str]:
    lowered = raw_text.lower()
    hints = []
    rules = [
        ("report_card", ("report card", "marksheet", "mark sheet", "grade report", "roll number")),
        ("transcript", ("cgpa", "semester", "transcript")),
        ("certificate", ("certificate", "course completion")),
        ("identity_document", ("passport", "aadhaar", "pan", "date of birth", "holder name")),
        ("academic_record", ("university", "college", "school", "board", "student")),
        ("financial_document", ("tax", "invoice", "balance", "account", "amount")),
    ]
    for hint, keywords in rules:
        if any(keyword in lowered for keyword in keywords):
            hints.append(hint)
    return hints or ["generic_pdf_evidence"]


def _detect_pii_categories(raw_text: str) -> List[str]:
    lowered = raw_text.lower()
    categories = []
    if EMAIL_PATTERN.search(raw_text):
        categories.append("email")
    if PHONE_PATTERN.search(raw_text):
        categories.append("phone_number")
    if "date of birth" in lowered or "dob" in lowered or "birth date" in lowered:
        categories.append("date_of_birth")
    if "address" in lowered:
        categories.append("address")
    if any(token in lowered for token in ("aadhaar", "pan", "passport")):
        categories.append("government_identifier")
    return sorted(set(categories))


def _issuer_hints(evidence_lines: Sequence[EvidenceLine]) -> List[str]:
    hints = []
    for line in evidence_lines:
        lowered = line.text.lower()
        if any(keyword in lowered for keyword in ("university", "college", "institute", "school", "board", "authority")):
            hints.append(line.text)
    return hints[:10]


def _structure_notes(
    family_hints: Sequence[str],
    sections: Sequence[str],
    page_profiles: Sequence[PageStructureProfile],
) -> List[str]:
    notes = [f"Document family hints: {', '.join(family_hints)}."]
    if sections:
        notes.append(f"Detected sections: {', '.join(sections[:8])}.")
    if any(profile.likely_table for profile in page_profiles):
        notes.append("At least one page appears table-like.")
    if any(profile.likely_form for profile in page_profiles):
        notes.append("At least one page appears form-like with label/value pairs.")
    return notes


def _resolve_label_config(label_text: str):
    normalized = label_text.strip().lower()
    for key, value in LABEL_CONFIG.items():
        if normalized == key or normalized.endswith(key) or key in normalized:
            return value
    return None


def _normalize_value(value: str, category: str) -> str:
    cleaned = " ".join(str(value).strip().split())
    if category == "email":
        return cleaned.lower()
    if category == "phone_number":
        digits = re.sub(r"\D", "", cleaned)
        return digits[-10:] if len(digits) >= 10 else digits
    if category in {"document_number", "registration_number", "license_number", "tax_identifier", "national_identifier"}:
        return cleaned.upper().replace(" ", "")
    if category in {"date_of_birth", "issue_date", "expiry_date", "date_reference"}:
        parsed = _try_parse_date(cleaned)
        return parsed or cleaned
    return cleaned


def _try_parse_date(value: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%b %Y", "%B %Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _find_evidence_for_value(value: str, evidence_lines: Sequence[EvidenceLine]) -> tuple[int, str]:
    normalized = value.lower()
    for line in evidence_lines:
        if normalized in line.text.lower():
            return line.page, line.text
    return (evidence_lines[0].page, evidence_lines[0].text) if evidence_lines else (1, value)


def _dedupe_candidates(candidates: Iterable[FieldCandidate]) -> List[FieldCandidate]:
    grouped: dict[tuple[int, str, str], FieldCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: (-item.confidence, len(item.raw_value), item.label)):
        key = (candidate.page, candidate.category, candidate.normalized_value.lower())
        if key not in grouped:
            grouped[key] = candidate
    return sorted(grouped.values(), key=lambda item: (item.page, -item.confidence, item.label))


def _dedupe_credentials(credentials: Iterable[ExtractedCredential]) -> List[ExtractedCredential]:
    grouped: dict[tuple[int, str, str], ExtractedCredential] = {}
    for credential in sorted(credentials, key=lambda item: (-item.confidence, len(item.value), item.label)):
        key = (credential.page, credential.category, credential.normalized_value.lower())
        if key not in grouped:
            grouped[key] = credential
    return sorted(grouped.values(), key=lambda item: (item.page, -item.confidence, item.label))


def _suggest_verifier_key(category: str, family_hints: Sequence[str]) -> str:
    verifier_map = {
        "person_name": "identity_registry",
        "date_of_birth": "identity_registry",
        "email": "identity_registry",
        "phone_number": "identity_registry",
        "address": "identity_registry",
        "issuer": "institution_registry",
        "credential_title": "credential_registry",
        "registration_number": "records_registry",
        "document_number": "issuer_portal",
        "license_number": "issuer_portal",
        "score": "records_registry",
        "tax_identifier": "government_registry",
        "national_identifier": "government_registry",
    }
    if category in verifier_map:
        return verifier_map[category]
    if "financial_document" in family_hints:
        return "financial_registry"
    return "manual_review"


def _candidate_id(label: str, value: str, page: int) -> str:
    return f"cand_{hashlib.sha1(f'{label}|{value}|{page}'.encode('utf-8')).hexdigest()[:12]}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _canonical_label(category: str) -> str:
    return CANONICAL_LABELS.get(category, category)


def _is_section_header(text: str) -> bool:
    normalized = text.lower().strip().strip(":")
    return normalized in {"education", "experience", "skills", "report card", "marksheet", "student details", "academic details"} or (text.isupper() and len(text.split()) <= 5)


def _looks_like_table_row(text: str) -> bool:
    cells = [part for part in re.split(r"\s{2,}|\t", text) if part]
    numeric_cells = sum(1 for cell in cells if any(char.isdigit() for char in cell))
    return len(cells) >= 3 and numeric_cells >= 2
