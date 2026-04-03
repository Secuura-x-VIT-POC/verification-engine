from collections import defaultdict
from datetime import datetime
import hashlib
import re
from typing import List, Sequence

from extraction.grounding.spatial_locator import MIN_ACCEPTED_CONFIDENCE, ground_value_to_spatial_map
from extraction.schema.models import (
    BoundingBox,
    CredentialAudit,
    DocumentProfile,
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
DATE_PATTERN = re.compile(
    r"\b(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{4}\s*-\s*(?:Present|\d{4})\b|\b\d{2}[/-]\d{2}[/-]\d{4}\b|\b\d{4}\s*-\s*\d{4}\b",
    re.IGNORECASE,
)
ID_PATTERN = re.compile(r"\b[A-Z]{2,5}\d{5,16}\b")
AMOUNT_PATTERN = re.compile(r"(?:INR|Rs\.?|USD|\$)\s?[0-9,]+(?:\.[0-9]{1,2})?|\b[0-9,]+\.[0-9]{2}\b")
PERCENT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?%|\bCGPA\s*[-:]?\s*\d+(?:\.\d+)?/?10\b", re.IGNORECASE)
ADDRESS_PATTERN = re.compile(r"\b(?:address|addr)\b", re.IGNORECASE)
GOV_ID_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b")

SECTION_STOP_WORDS = {
    "education",
    "experience",
    "projects",
    "skills",
    "technical competencies",
    "extracurricular activities",
    "certifications",
    "licenses",
    "identity",
    "financial",
    "summary",
    "profile",
}

LABEL_CONFIG = {
    "name": ("person_name", True, "identity_registry"),
    "candidate_name": ("person_name", True, "identity_registry"),
    "full name": ("person_name", True, "identity_registry"),
    "student name": ("person_name", True, "identity_registry"),
    "institution": ("issuer", False, "institution_registry"),
    "issuer": ("issuer", False, "institution_registry"),
    "university": ("issuer", False, "institution_registry"),
    "degree": ("credential_title", False, "credential_registry"),
    "credential": ("credential_title", False, "credential_registry"),
    "certificate": ("credential_title", False, "credential_registry"),
    "course": ("program_name", False, "institution_registry"),
    "branch": ("program_branch", False, "institution_registry"),
    "score": ("score", False, "records_registry"),
    "cgpa": ("score", False, "records_registry"),
    "grade": ("score", False, "records_registry"),
    "dob": ("date_of_birth", True, "identity_registry"),
    "date of birth": ("date_of_birth", True, "identity_registry"),
    "expiry": ("expiry_date", False, "issuer_portal"),
    "expiry date": ("expiry_date", False, "issuer_portal"),
    "issue date": ("issue_date", False, "issuer_portal"),
    "registration number": ("registration_number", False, "records_registry"),
    "registration no": ("registration_number", False, "records_registry"),
    "roll number": ("registration_number", False, "records_registry"),
    "document number": ("document_number", False, "issuer_portal"),
    "license number": ("license_number", False, "issuer_portal"),
    "email": ("email", True, "identity_registry"),
    "phone": ("phone_number", True, "identity_registry"),
    "mobile": ("phone_number", True, "identity_registry"),
    "address": ("address", True, "identity_registry"),
    "pan": ("tax_identifier", True, "government_registry"),
    "aadhaar": ("national_identifier", True, "government_registry"),
    "tax": ("financial_amount", False, "financial_registry"),
}

CATEGORY_TO_CANONICAL_LABEL = {
    "person_name": "name",
    "issuer": "issuer",
    "credential_title": "credential_title",
    "program_name": "program_name",
    "program_branch": "program_branch",
    "score": "score",
    "date_of_birth": "date_of_birth",
    "expiry_date": "expiry_date",
    "issue_date": "issue_date",
    "registration_number": "registration_number",
    "document_number": "document_id",
    "license_number": "license_number",
    "email": "email",
    "phone_number": "phone_number",
    "address": "address",
    "tax_identifier": "tax_identifier",
    "national_identifier": "national_identifier",
    "financial_amount": "amount",
    "date_reference": "date",
}


def build_generalized_analysis(
    raw_text: str,
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    warnings: List[ExtractionWarning],
) -> tuple[List[EvidenceLine], List[FieldCandidate], GeneralizedAnalysisPayload]:
    evidence_lines = build_evidence_lines(spatial_text_map)
    document_profile = build_document_profile(raw_text, evidence_lines, extraction_method)
    field_candidates = extract_field_candidates(raw_text, evidence_lines, spatial_text_map, extraction_method, warnings)
    field_candidates = _deduplicate_candidates(field_candidates)
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
    return evidence_lines, field_candidates, payload


def build_evidence_lines(spatial_text_map: Sequence[SpatialTextToken]) -> List[EvidenceLine]:
    lines: List[EvidenceLine] = []
    grouped_by_page: dict[int, list[tuple[int, SpatialTextToken]]] = defaultdict(list)
    for index, token in enumerate(spatial_text_map):
        grouped_by_page[token.page].append((index, token))

    for page, indexed_tokens in grouped_by_page.items():
        indexed_tokens.sort(key=lambda item: (round(item[1].bbox[1], 1), item[1].bbox[0]))
        current_indices: List[int] = []
        current_tokens: List[SpatialTextToken] = []
        current_y: float | None = None

        for index, token in indexed_tokens:
            token_y = token.bbox[1]
            if current_y is None or abs(token_y - current_y) <= 4.0:
                current_indices.append(index)
                current_tokens.append(token)
                current_y = token_y if current_y is None else min(current_y, token_y)
                continue

            lines.append(_tokens_to_line(page, current_tokens, current_indices))
            current_indices = [index]
            current_tokens = [token]
            current_y = token_y

        if current_tokens:
            lines.append(_tokens_to_line(page, current_tokens, current_indices))

    return lines


def build_document_profile(raw_text: str, evidence_lines: Sequence[EvidenceLine], extraction_method: str) -> DocumentProfile:
    sections = _detect_sections(evidence_lines)
    page_profiles = _build_page_profiles(evidence_lines, extraction_method)
    family_hints = _document_family_hints(raw_text, sections)
    pii_categories = _detect_pii_categories(raw_text)
    issuer_hints = _issuer_hints(evidence_lines)
    likely_tables_present = any(page_profile.likely_table for page_profile in page_profiles)
    likely_form_present = any(page_profile.likely_form for page_profile in page_profiles)
    return DocumentProfile(
        document_family_hints=family_hints,
        contains_pii=bool(pii_categories),
        pii_categories=pii_categories,
        likely_sections=sections,
        likely_tables_present=likely_tables_present,
        likely_form_present=likely_form_present,
        issuer_hints=issuer_hints,
        structure_notes=_structure_notes(family_hints, sections, likely_tables_present, likely_form_present),
        page_profiles=page_profiles,
    )


def extract_field_candidates(
    raw_text: str,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    warnings: List[ExtractionWarning],
) -> List[FieldCandidate]:
    candidates: List[FieldCandidate] = []
    seen = set()

    for line in evidence_lines:
        line_candidates = _extract_labelled_candidates_from_line(line, spatial_text_map, extraction_method)
        for candidate in line_candidates:
            key = (candidate.label, candidate.normalized_value, candidate.page)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    candidates.extend(_extract_pattern_candidates(raw_text, evidence_lines, spatial_text_map, extraction_method, seen))
    candidates.extend(_extract_institution_and_title_candidates(evidence_lines, spatial_text_map, extraction_method, seen))
    candidates.extend(_extract_identity_and_address_candidates(raw_text, evidence_lines, spatial_text_map, extraction_method, seen))

    confidence_filtered = [candidate for candidate in candidates if candidate.confidence >= MIN_ACCEPTED_CONFIDENCE]
    low_confidence_dropped = len(candidates) - len(confidence_filtered)
    if low_confidence_dropped:
        warnings.append(
            ExtractionWarning(
                code="LOW_CONFIDENCE_CANDIDATES_DROPPED",
                message=f"{low_confidence_dropped} low-confidence field candidates were removed during normalization.",
            )
        )
    filtered = _suppress_overlapping_candidates(confidence_filtered)
    overlap_dropped = len(confidence_filtered) - len(filtered)
    if overlap_dropped:
        warnings.append(
            ExtractionWarning(
                code="OVERLAPPING_CANDIDATES_SUPPRESSED",
                message=f"{overlap_dropped} overlapping field candidates were suppressed in favor of more canonical grounded claims.",
            )
        )
    filtered.sort(key=lambda candidate: (candidate.page, -candidate.confidence, candidate.label, candidate.normalized_value))
    return filtered


def build_credentials(field_candidates: Sequence[FieldCandidate]) -> List[ExtractedCredential]:
    credentials: List[ExtractedCredential] = []
    for candidate in field_candidates:
        credential_id = f"cred_{hashlib.sha1(candidate.candidate_id.encode('utf-8')).hexdigest()[:10]}"
        credentials.append(
            ExtractedCredential(
                credential_id=credential_id,
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
    return _deduplicate_credentials(credentials)


def build_verification_plan(
    credentials: Sequence[ExtractedCredential],
    document_profile: DocumentProfile,
) -> List[VerificationPlanItem]:
    plan_items: List[VerificationPlanItem] = []
    for index, credential in enumerate(credentials, start=1):
        verifier_key = _suggest_verifier_key(credential.category, document_profile.document_family_hints)
        priority = "high" if credential.requires_verification and not credential.is_pii else "medium"
        plan_items.append(
            VerificationPlanItem(
                plan_item_id=f"plan_{index:03d}",
                credential_id=credential.credential_id,
                verifier_key=verifier_key,
                verifier_type="deterministic_lookup",
                priority=priority,
                reason=credential.verification_reason or f"Verify {credential.label} against {verifier_key}.",
            )
        )
    return plan_items


def build_credential_audits(credentials: Sequence[ExtractedCredential]) -> List[CredentialAudit]:
    audits: List[CredentialAudit] = []
    for index, credential in enumerate(credentials, start=1):
        audits.append(
            CredentialAudit(
                audit_id=f"audit_{index:03d}",
                credential_id=credential.credential_id,
                label=credential.label,
                status="extracted",
                confidence=credential.confidence,
                evidence=credential.source_text,
                page=credential.page,
                bounding_box=credential.bounding_box,
                explanation=f"{credential.label} was deterministically extracted and grounded from the PDF.",
                source_provenance=f"page {credential.page} / method={credential.extraction_method}",
            )
        )
    return audits


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


def _tokens_to_line(page: int, tokens: Sequence[SpatialTextToken], token_indices: Sequence[int]) -> EvidenceLine:
    text = " ".join(token.text for token in tokens).strip()
    return EvidenceLine(
        page=page,
        text=text,
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


def _detect_sections(evidence_lines: Sequence[EvidenceLine]) -> List[str]:
    sections = []
    for line in evidence_lines:
        text = line.text.strip()
        if not text:
            continue
        normalized = text.lower().strip(":")
        if normalized in SECTION_STOP_WORDS or (text.isupper() and len(text.split()) <= 5):
            if normalized not in sections:
                sections.append(normalized)
    return sections


def _build_page_profiles(evidence_lines: Sequence[EvidenceLine], extraction_method: str) -> List[PageStructureProfile]:
    page_groups: dict[int, List[EvidenceLine]] = defaultdict(list)
    for line in evidence_lines:
        page_groups[line.page].append(line)

    profiles = []
    for page, lines in sorted(page_groups.items()):
        section_headers = [line.text for line in lines if line.text.isupper() or line.text.lower().strip(":") in SECTION_STOP_WORDS]
        likely_table = any(_looks_like_table_row(line.text) for line in lines)
        likely_form = any(":" in line.text and len(line.text.split(":")[0].split()) <= 4 for line in lines)
        word_count = sum(len(line.text.split()) for line in lines)
        character_density = round(sum(len(line.text) for line in lines) / max(len(lines), 1), 4)
        profiles.append(
            PageStructureProfile(
                page=page,
                extraction_method=extraction_method,
                word_count=word_count,
                character_density=character_density,
                section_headers=section_headers[:12],
                likely_table=likely_table,
                likely_form=likely_form,
            )
        )
    return profiles


def _document_family_hints(raw_text: str, sections: Sequence[str]) -> List[str]:
    lowered = raw_text.lower()
    hints = []
    hint_rules = [
        ("transcript", ("cgpa", "semester", "grade", "transcript")),
        ("certificate", ("certificate", "certified", "course completion")),
        ("identity_document", ("passport", "aadhaar", "pan", "date of birth", "address")),
        ("license", ("license", "licence", "permit", "registration authority")),
        ("financial_document", ("tax", "invoice", "amount", "balance", "account")),
        ("academic_record", ("university", "college", "education", "degree")),
    ]
    for hint, keywords in hint_rules:
        if any(keyword in lowered for keyword in keywords):
            hints.append(hint)
    if not hints and sections:
        hints.append("structured_supporting_document")
    if not hints:
        hints.append("generic_pdf_evidence")
    return hints


def _detect_pii_categories(raw_text: str) -> List[str]:
    categories = []
    lowered = raw_text.lower()
    if EMAIL_PATTERN.search(raw_text):
        categories.append("email")
    if PHONE_PATTERN.search(raw_text):
        categories.append("phone_number")
    if "date of birth" in lowered or re.search(r"\bdob\b", lowered):
        categories.append("date_of_birth")
    if ADDRESS_PATTERN.search(raw_text):
        categories.append("address")
    if any(token in lowered for token in ("aadhaar", "pan", "passport", "national id")):
        categories.append("government_identifier")
    return sorted(set(categories))


def _issuer_hints(evidence_lines: Sequence[EvidenceLine]) -> List[str]:
    hints = []
    for line in evidence_lines:
        lowered = line.text.lower()
        if any(keyword in lowered for keyword in ("university", "institute", "college", "authority", "board", "department")):
            hints.append(line.text)
    return hints[:10]


def _structure_notes(
    family_hints: Sequence[str],
    sections: Sequence[str],
    likely_tables_present: bool,
    likely_form_present: bool,
) -> List[str]:
    notes = []
    notes.append(f"Document family hints: {', '.join(family_hints)}.")
    if sections:
        notes.append(f"Detected sections: {', '.join(sections[:8])}.")
    if likely_tables_present:
        notes.append("At least one page appears table-like and may contain row/cell evidence.")
    if likely_form_present:
        notes.append("At least one page appears form-like with label/value pairs.")
    return notes


def _extract_labelled_candidates_from_line(
    line: EvidenceLine,
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
) -> List[FieldCandidate]:
    text = line.text
    matches = re.findall(r"([A-Za-z][A-Za-z /&()-]{1,40})\s*[:\-]\s*(.+)", text)
    candidates = []
    for label_text, value_text in matches:
        normalized_label = label_text.strip().lower()
        config = _resolve_label_config(normalized_label)
        if config is None:
            continue
        category, is_pii, verifier_key = config
        normalized_value = _normalize_value(value_text.strip(), category)
        bbox, confidence, match_type = ground_value_to_spatial_map(value_text.strip(), spatial_text_map)
        if confidence < MIN_ACCEPTED_CONFIDENCE:
            continue
        candidates.append(
            FieldCandidate(
                candidate_id=_candidate_id(label_text, value_text, line.page),
                label=_canonical_label(normalized_label, category),
                category=category,
                raw_value=value_text.strip(),
                normalized_value=normalized_value,
                source_text=text,
                evidence_snippet=text,
                page=line.page,
                bounding_box=bbox[0] if bbox else line.bbox,
                confidence=confidence,
                grounding_match_type=match_type,
                is_pii=is_pii,
                requires_verification=True,
                verification_reason=f"{label_text.strip()} should be checked via {verifier_key}.",
                extraction_method=extraction_method,
                source=line.source,
            )
        )
    return candidates


def _extract_pattern_candidates(
    raw_text: str,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    seen: set,
) -> List[FieldCandidate]:
    pattern_specs = [
        ("email", "email", EMAIL_PATTERN, True, "identity_registry"),
        ("phone_number", "phone_number", PHONE_PATTERN, True, "identity_registry"),
        ("document_id", "document_number", ID_PATTERN, False, "issuer_portal"),
        ("date", "date_reference", DATE_PATTERN, False, "issuer_portal"),
        ("amount", "financial_amount", AMOUNT_PATTERN, False, "financial_registry"),
        ("score", "score", PERCENT_PATTERN, False, "records_registry"),
        ("government_identifier", "national_identifier", GOV_ID_PATTERN, True, "government_registry"),
    ]
    candidates: List[FieldCandidate] = []
    for label, category, pattern, is_pii, verifier_key in pattern_specs:
        for match in pattern.finditer(raw_text):
            value = match.group(0).strip()
            bbox, confidence, match_type = ground_value_to_spatial_map(value, spatial_text_map)
            if confidence < MIN_ACCEPTED_CONFIDENCE:
                continue
            page, snippet = _find_evidence_for_value(value, evidence_lines)
            candidate = FieldCandidate(
                candidate_id=_candidate_id(label, value, page),
                label=label,
                category=category,
                raw_value=value,
                normalized_value=_normalize_value(value, category),
                source_text=snippet,
                evidence_snippet=snippet,
                page=page,
                bounding_box=bbox[0] if bbox else None,
                confidence=confidence,
                grounding_match_type=match_type,
                is_pii=is_pii,
                requires_verification=True,
                verification_reason=f"{label} should be checked via {verifier_key}.",
                extraction_method=extraction_method,
            )
            key = (candidate.label, candidate.normalized_value, candidate.page)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def _extract_identity_and_address_candidates(
    raw_text: str,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    seen: set,
) -> List[FieldCandidate]:
    candidates: List[FieldCandidate] = []
    date_of_birth_patterns = [
        re.compile(r"(?i)(?:date of birth|dob)\s*[:\-]\s*([^\n]+)"),
        re.compile(r"(?i)\bDOB\b\s*[:\-]?\s*([^\n]+)"),
    ]

    for pattern in date_of_birth_patterns:
        for match in pattern.finditer(raw_text):
            value = match.group(1).strip()
            page, snippet = _find_evidence_for_value(value, evidence_lines)
            bbox, confidence, match_type = ground_value_to_spatial_map(value, spatial_text_map)
            if confidence < MIN_ACCEPTED_CONFIDENCE:
                continue
            candidate = FieldCandidate(
                candidate_id=_candidate_id("date_of_birth", value, page),
                label="date_of_birth",
                category="date_of_birth",
                raw_value=value,
                normalized_value=_normalize_value(value, "date_of_birth"),
                source_text=snippet,
                evidence_snippet=snippet,
                page=page,
                bounding_box=bbox[0] if bbox else None,
                confidence=confidence,
                grounding_match_type=match_type,
                is_pii=True,
                requires_verification=True,
                verification_reason="Date of birth should be checked via identity_registry.",
                extraction_method=extraction_method,
            )
            key = (candidate.label, candidate.normalized_value, candidate.page)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    for line in evidence_lines:
        lowered = line.text.lower()
        if "address" not in lowered:
            continue
        value = line.text.split(":", 1)[1].strip() if ":" in line.text else line.text
        candidates.extend(
            _make_candidate(
                label="address",
                category="address",
                value=value,
                evidence_line=line,
                spatial_text_map=spatial_text_map,
                extraction_method=extraction_method,
                is_pii=True,
                verification_reason="Address should be checked via identity_registry or manual review.",
                seen=seen,
            )
        )
    return candidates


def _extract_institution_and_title_candidates(
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    seen: set,
) -> List[FieldCandidate]:
    candidates: List[FieldCandidate] = []
    for line in evidence_lines:
        lowered = line.text.lower()
        if any(keyword in lowered for keyword in ("university", "institute", "college", "board", "authority", "department")):
            candidates.extend(
                _make_candidate(
                    label="issuer",
                    category="issuer",
                    value=line.text,
                    evidence_line=line,
                    spatial_text_map=spatial_text_map,
                    extraction_method=extraction_method,
                    is_pii=False,
                    verification_reason="Issuer should be verified against an institution or registry source.",
                    seen=seen,
                )
            )
        if any(keyword in lowered for keyword in ("certificate", "degree", "bachelor", "master", "diploma", "license", "transcript")):
            candidates.extend(
                _make_candidate(
                    label="credential_title",
                    category="credential_title",
                    value=line.text,
                    evidence_line=line,
                    spatial_text_map=spatial_text_map,
                    extraction_method=extraction_method,
                    is_pii=False,
                    verification_reason="Credential title should be matched against issuer records.",
                    seen=seen,
                )
            )
    return candidates


def _make_candidate(
    label: str,
    category: str,
    value: str,
    evidence_line: EvidenceLine,
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    is_pii: bool,
    verification_reason: str,
    seen: set,
) -> List[FieldCandidate]:
    bbox, confidence, match_type = ground_value_to_spatial_map(value, spatial_text_map)
    if confidence < MIN_ACCEPTED_CONFIDENCE:
        return []
    candidate = FieldCandidate(
        candidate_id=_candidate_id(label, value, evidence_line.page),
        label=label,
        category=category,
        raw_value=value,
        normalized_value=_normalize_value(value, category),
        source_text=evidence_line.text,
        evidence_snippet=evidence_line.text,
        page=evidence_line.page,
        bounding_box=bbox[0] if bbox else evidence_line.bbox,
        confidence=confidence,
        grounding_match_type=match_type,
        is_pii=is_pii,
        requires_verification=True,
        verification_reason=verification_reason,
        extraction_method=extraction_method,
        source=evidence_line.source,
    )
    key = (candidate.label, candidate.normalized_value, candidate.page)
    if key in seen:
        return []
    seen.add(key)
    return [candidate]


def _deduplicate_candidates(field_candidates: Sequence[FieldCandidate]) -> List[FieldCandidate]:
    grouped: dict[tuple[int, str, str], FieldCandidate] = {}
    for candidate in sorted(field_candidates, key=lambda item: (-item.confidence, len(item.raw_value), item.label)):
        key = (candidate.page, candidate.category, candidate.normalized_value.lower())
        existing = grouped.get(key)
        if existing is None or _candidate_rank(candidate) > _candidate_rank(existing):
            grouped[key] = candidate
    return sorted(grouped.values(), key=lambda candidate: (candidate.page, -candidate.confidence, candidate.category, candidate.normalized_value))


def _deduplicate_credentials(credentials: Sequence[ExtractedCredential]) -> List[ExtractedCredential]:
    grouped: dict[tuple[int, str, str], ExtractedCredential] = {}
    for credential in sorted(credentials, key=lambda item: (-item.confidence, len(item.value), item.label)):
        key = (credential.page, credential.category, credential.normalized_value.lower())
        existing = grouped.get(key)
        if existing is None or _credential_rank(credential) > _credential_rank(existing):
            grouped[key] = credential
    return sorted(grouped.values(), key=lambda credential: (credential.page, -credential.confidence, credential.category, credential.normalized_value))


def _candidate_rank(candidate: FieldCandidate) -> tuple[float, int, int]:
    return (candidate.confidence, 1 if ":" not in candidate.raw_value else 0, len(candidate.raw_value))


def _credential_rank(credential: ExtractedCredential) -> tuple[float, int, int]:
    return (credential.confidence, 1 if ":" not in credential.value else 0, len(credential.value))


def _suggest_verifier_key(category: str, family_hints: Sequence[str]) -> str:
    verifier_map = {
        "person_name": "identity_registry",
        "email": "identity_registry",
        "phone_number": "identity_registry",
        "date_of_birth": "identity_registry",
        "address": "identity_registry",
        "issuer": "institution_registry",
        "credential_title": "credential_registry",
        "registration_number": "records_registry",
        "document_number": "issuer_portal",
        "license_number": "issuer_portal",
        "financial_amount": "financial_registry",
        "score": "records_registry",
        "tax_identifier": "government_registry",
        "national_identifier": "government_registry",
        "issue_date": "issuer_portal",
        "expiry_date": "issuer_portal",
    }
    if category in verifier_map:
        return verifier_map[category]
    if "financial_document" in family_hints:
        return "financial_registry"
    return "manual_review"


def _candidate_id(label: str, value: str, page: int) -> str:
    digest = hashlib.sha1(f"{label}|{value}|{page}".encode("utf-8")).hexdigest()
    return f"cand_{digest[:12]}"


def _resolve_label_config(label: str):
    for key, value in LABEL_CONFIG.items():
        if key == label or label.endswith(key) or key in label:
            return value
    return None


def _canonical_label(label: str, category: str | None = None) -> str:
    if category:
        return CATEGORY_TO_CANONICAL_LABEL.get(category, label.strip().lower().replace(" ", "_"))
    return label.strip().lower().replace(" ", "_")


def _normalize_value(value: str, category: str) -> str:
    cleaned = " ".join(value.strip().split())
    if category in {"email"}:
        return cleaned.lower()
    if category in {"phone_number"}:
        digits = re.sub(r"\D", "", cleaned)
        return digits[-10:] if len(digits) >= 10 else digits
    if category in {"financial_amount"}:
        return cleaned.replace(",", "")
    if category in {"registration_number", "document_number", "license_number", "tax_identifier", "national_identifier"}:
        return cleaned.upper()
    if category in {"date_of_birth", "issue_date", "expiry_date", "date_reference"}:
        parsed = _try_parse_date(cleaned)
        return parsed if parsed else cleaned
    return cleaned


def _try_parse_date(value: str) -> str | None:
    date_formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%b %Y",
        "%B %Y",
    ]
    for date_format in date_formats:
        try:
            parsed = datetime.strptime(value, date_format)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _find_evidence_for_value(value: str, evidence_lines: Sequence[EvidenceLine]) -> tuple[int, str]:
    normalized_value = value.lower()
    for line in evidence_lines:
        if normalized_value in line.text.lower():
            return line.page, line.text
    return (evidence_lines[0].page, evidence_lines[0].text) if evidence_lines else (1, value)


def _looks_like_table_row(text: str) -> bool:
    pieces = [piece for piece in re.split(r"\s{2,}|\t", text) if piece]
    numeric_cells = sum(1 for piece in pieces if any(char.isdigit() for char in piece))
    return len(pieces) >= 3 and numeric_cells >= 2


def _suppress_overlapping_candidates(field_candidates: Sequence[FieldCandidate]) -> List[FieldCandidate]:
    by_page: dict[int, List[FieldCandidate]] = defaultdict(list)
    for candidate in field_candidates:
        by_page[candidate.page].append(candidate)

    kept_ids = {candidate.candidate_id for candidate in field_candidates}
    for page_candidates in by_page.values():
        issue_dates = [candidate for candidate in page_candidates if candidate.category == "issue_date"]
        generic_dates = [candidate for candidate in page_candidates if candidate.category == "date_reference"]
        for generic_date in generic_dates:
            if any(issue_date.normalized_value == generic_date.normalized_value for issue_date in issue_dates):
                kept_ids.discard(generic_date.candidate_id)

        clean_issuers = [
            candidate
            for candidate in page_candidates
            if candidate.category == "issuer" and ":" not in candidate.raw_value
        ]
        broad_issuers = [
            candidate
            for candidate in page_candidates
            if candidate.category == "issuer" and ":" in candidate.raw_value
        ]
        for broad_issuer in broad_issuers:
            if any(clean_issuer.raw_value in broad_issuer.raw_value for clean_issuer in clean_issuers):
                kept_ids.discard(broad_issuer.candidate_id)

        clean_titles = [
            candidate
            for candidate in page_candidates
            if candidate.category == "credential_title" and ":" not in candidate.raw_value
        ]
        broad_titles = [
            candidate
            for candidate in page_candidates
            if candidate.category == "credential_title" and ":" in candidate.raw_value
        ]
        for broad_title in broad_titles:
            if any(clean_title.raw_value in broad_title.raw_value for clean_title in clean_titles):
                kept_ids.discard(broad_title.candidate_id)

    return [candidate for candidate in field_candidates if candidate.candidate_id in kept_ids]
