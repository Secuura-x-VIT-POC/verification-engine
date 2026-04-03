from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Iterable, List, Sequence

from extraction.grounding.spatial_locator import (
    MIN_ACCEPTED_CONFIDENCE,
    average_token_confidence,
    ground_value_to_spatial_map,
    merge_bounding_boxes,
    resolve_source_type,
    tokens_for_line,
)
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
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{4}-\d{4}\b", re.IGNORECASE)
ID_PATTERN = re.compile(r"\b[A-Z]{2,5}\d{5,16}\b")
PERCENT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?%|\bCGPA\s*[-:]?\s*\d+(?:\.\d+)?/?10\b", re.IGNORECASE)
GOV_ID_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z .'-]{2,}$")
AADHAAR_NUMBER_PATTERN = re.compile(r"^\d{12}$")
PAN_NUMBER_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
GRADE_VALUE_PATTERN = re.compile(r"^[A-F][+-]?$", re.IGNORECASE)
RESULT_STATUS_PATTERN = re.compile(r"\b(pass|passed|fail|failed|withheld|absent|promoted)\b", re.IGNORECASE)

LABEL_CONFIG = {
    "name": ("person_name", True, "identity_registry"),
    "candidate name": ("person_name", True, "identity_registry"),
    "full name": ("person_name", True, "identity_registry"),
    "student name": ("person_name", True, "identity_registry"),
    "holder name": ("person_name", True, "identity_registry"),
    "applicant name": ("person_name", True, "identity_registry"),
    "father name": ("person_name", True, "identity_registry"),
    "father's name": ("person_name", True, "identity_registry"),
    "mother name": ("person_name", True, "identity_registry"),
    "mother's name": ("person_name", True, "identity_registry"),
    "guardian name": ("person_name", True, "identity_registry"),
    "name of student": ("person_name", True, "identity_registry"),
    "institution": ("issuer", False, "institution_registry"),
    "institution name": ("issuer", False, "institution_registry"),
    "issuer": ("issuer", False, "institution_registry"),
    "university": ("issuer", False, "institution_registry"),
    "board": ("issuer", False, "institution_registry"),
    "board name": ("issuer", False, "institution_registry"),
    "school": ("issuer", False, "institution_registry"),
    "school name": ("issuer", False, "institution_registry"),
    "college": ("issuer", False, "institution_registry"),
    "college name": ("issuer", False, "institution_registry"),
    "degree": ("credential_title", False, "credential_registry"),
    "credential": ("credential_title", False, "credential_registry"),
    "certificate": ("credential_title", False, "credential_registry"),
    "course": ("program_name", False, "institution_registry"),
    "branch": ("program_branch", False, "institution_registry"),
    "score": ("score", False, "records_registry"),
    "cgpa": ("score", False, "records_registry"),
    "grade": ("score", False, "records_registry"),
    "marks": ("score", False, "records_registry"),
    "marks obtained": ("score", False, "records_registry"),
    "percentage": ("score", False, "records_registry"),
    "result": ("score", False, "records_registry"),
    "result status": ("score", False, "records_registry"),
    "dob": ("date_of_birth", True, "identity_registry"),
    "date of birth": ("date_of_birth", True, "identity_registry"),
    "birth date": ("date_of_birth", True, "identity_registry"),
    "year of birth": ("date_of_birth", True, "identity_registry"),
    "yob": ("date_of_birth", True, "identity_registry"),
    "issue date": ("issue_date", False, "issuer_portal"),
    "expiry date": ("expiry_date", False, "issuer_portal"),
    "registration number": ("registration_number", False, "records_registry"),
    "registration no": ("registration_number", False, "records_registry"),
    "register number": ("registration_number", False, "records_registry"),
    "register no": ("registration_number", False, "records_registry"),
    "roll number": ("registration_number", False, "records_registry"),
    "roll no": ("registration_number", False, "records_registry"),
    "roll no.": ("registration_number", False, "records_registry"),
    "seat number": ("registration_number", False, "records_registry"),
    "seat no": ("registration_number", False, "records_registry"),
    "seat no.": ("registration_number", False, "records_registry"),
    "document number": ("document_number", False, "issuer_portal"),
    "license number": ("license_number", False, "issuer_portal"),
    "email": ("email", True, "identity_registry"),
    "phone": ("phone_number", True, "identity_registry"),
    "mobile": ("phone_number", True, "identity_registry"),
    "address": ("address", True, "identity_registry"),
    "pan": ("tax_identifier", True, "government_registry"),
    "pan number": ("tax_identifier", True, "government_registry"),
    "permanent account number": ("tax_identifier", True, "government_registry"),
    "aadhaar": ("national_identifier", True, "government_registry"),
    "uid": ("national_identifier", True, "government_registry"),
    "aadhaar number": ("national_identifier", True, "government_registry"),
    "passport number": ("document_number", True, "issuer_portal"),
    "passport no": ("document_number", True, "issuer_portal"),
    "exam year": ("date_reference", False, "records_registry"),
    "year of passing": ("date_reference", False, "records_registry"),
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

SAME_LINE_BASE_CONFIDENCE = 0.98
NEARBY_RIGHT_BASE_CONFIDENCE = 0.9
NEARBY_BELOW_BASE_CONFIDENCE = 0.82
LOCAL_PATTERN_BASE_CONFIDENCE = 0.78
GLOBAL_PATTERN_BASE_CONFIDENCE = 0.72
CONTEXTUAL_PATTERN_BOOST = 0.08
NEIGHBOR_VERTICAL_GAP = 28.0
NEIGHBOR_HORIZONTAL_GAP = 80.0


@dataclass(frozen=True)
class LineContext:
    line: EvidenceLine
    tokens: list[SpatialTextToken]


@dataclass(frozen=True)
class CandidateProvenance:
    source_text: str
    evidence_snippet: str
    page: int
    bounding_box: BoundingBox | None
    context_bounding_box: BoundingBox | None
    confidence: float
    grounding_match_type: str
    provenance_method: str
    provenance_confidence: float
    source: str
    source_engine: str


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
    line_contexts = _build_line_contexts(evidence_lines, spatial_text_map)
    family_hints = _document_family_hints(raw_text)

    for index, line_context in enumerate(line_contexts):
        candidates.extend(
            _extract_label_candidates(
                line_contexts=line_contexts,
                line_index=index,
                extraction_method=extraction_method,
                seen=seen,
                family_hints=family_hints,
            )
        )

    candidates.extend(
        _extract_pattern_candidates(
            raw_text,
            line_contexts,
            extraction_method,
            seen,
            family_hints=family_hints,
        )
    )
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
    *,
    line_contexts: Sequence[LineContext],
    line_index: int,
    extraction_method: str,
    seen: set[tuple[str, str, int]],
    family_hints: Sequence[str],
) -> list[FieldCandidate]:
    line_context = line_contexts[line_index]
    binding = _match_label_prefix(line_context.line.text)
    if binding is None:
        return []

    label_text, inline_value = binding
    config = _resolve_label_config(label_text)
    if config is None:
        return []

    category, is_pii, verifier_key = config
    provenance: CandidateProvenance | None = None
    value_text = (inline_value or "").strip()
    if value_text:
        provenance = _build_local_provenance(
            line_context=line_context,
            label_text=label_text,
            value_text=value_text,
            provenance_method="same_line",
            base_confidence=SAME_LINE_BASE_CONFIDENCE,
        )
    else:
        provenance = _find_neighboring_value_provenance(
            line_contexts=line_contexts,
            line_index=line_index,
            label_text=label_text,
            category=category,
            family_hints=family_hints,
        )

    if provenance is None or not provenance.source_text:
        return []

    semantic_label, semantic_category, semantic_is_pii = _resolve_semantic_assignment(
        raw_label=label_text,
        base_category=category,
        value_text=provenance.source_text,
        line_contexts=line_contexts,
        line_index=line_index,
        family_hints=family_hints,
    )
    normalized_value = _normalize_value(provenance.source_text, semantic_category)
    key = (semantic_label, normalized_value, provenance.page)
    if key in seen:
        return []

    seen.add(key)
    return [
        FieldCandidate(
            candidate_id=_candidate_id(label_text, provenance.source_text, provenance.page),
            label=semantic_label,
            category=semantic_category,
            raw_value=provenance.source_text,
            normalized_value=normalized_value,
            source_text=provenance.source_text,
            evidence_snippet=provenance.evidence_snippet,
            page=provenance.page,
            bounding_box=provenance.bounding_box,
            context_bounding_box=provenance.context_bounding_box,
            confidence=provenance.confidence,
            grounding_match_type=provenance.grounding_match_type,
            provenance_method=provenance.provenance_method,
            provenance_confidence=provenance.provenance_confidence,
            is_pii=semantic_is_pii if semantic_is_pii is not None else is_pii,
            requires_verification=True,
            verification_reason=f"{label_text.strip()} should be checked via {verifier_key}.",
            extraction_method=extraction_method,
            source=provenance.source,
            source_engine=provenance.source_engine,
        )
    ]


def _extract_pattern_candidates(
    raw_text: str,
    line_contexts: Sequence[LineContext],
    extraction_method: str,
    seen: set[tuple[str, str, int]],
    *,
    family_hints: Sequence[str],
) -> list[FieldCandidate]:
    specs = [
        ("email", "email", EMAIL_PATTERN, True, "identity_registry"),
        ("phone_number", "phone_number", PHONE_PATTERN, True, "identity_registry"),
        ("date", "date_reference", DATE_PATTERN, False, "issuer_portal"),
        ("government_identifier", "national_identifier", GOV_ID_PATTERN, True, "government_registry"),
        ("document_id", "document_number", ID_PATTERN, False, "issuer_portal"),
        ("score", "score", PERCENT_PATTERN, False, "records_registry"),
        ("year", "date_reference", YEAR_PATTERN, False, "records_registry"),
        ("result", "score", RESULT_STATUS_PATTERN, False, "records_registry"),
    ]
    output = []
    for line_index, line_context in enumerate(line_contexts):
        for label, category, pattern, is_pii, verifier_key in specs:
            for match in pattern.finditer(line_context.line.text):
                value = match.group(0).strip()
                if label == "year" and DATE_PATTERN.search(line_context.line.text):
                    continue
                contextual = _resolve_pattern_context(
                    default_label=label,
                    default_category=category,
                    line_contexts=line_contexts,
                    line_index=line_index,
                    value=value,
                    family_hints=family_hints,
                )
                if not contextual:
                    continue
                normalized_value = _normalize_value(value, contextual["category"])
                key = (contextual["label"], normalized_value, line_context.line.page)
                if key in seen:
                    continue
                provenance = _build_pattern_provenance(
                    line_contexts=line_contexts,
                    line_index=line_index,
                    value_text=value,
                    label_text=contextual.get("context_label"),
                    contextualized=bool(contextual.get("context_label")),
                )
                if provenance is None:
                    continue
                seen.add(key)
                output.append(
                    FieldCandidate(
                        candidate_id=_candidate_id(contextual["label"], provenance.source_text, provenance.page),
                        label=contextual["label"],
                        category=contextual["category"],
                        raw_value=provenance.source_text,
                        normalized_value=normalized_value,
                        source_text=provenance.source_text,
                        evidence_snippet=provenance.evidence_snippet,
                        page=provenance.page,
                        bounding_box=provenance.bounding_box,
                        context_bounding_box=provenance.context_bounding_box,
                        confidence=provenance.confidence,
                        grounding_match_type=provenance.grounding_match_type,
                        provenance_method=provenance.provenance_method,
                        provenance_confidence=provenance.provenance_confidence,
                        is_pii=contextual["is_pii"] if contextual.get("is_pii") is not None else is_pii,
                        requires_verification=True,
                        verification_reason=f"{contextual['label']} should be checked via {verifier_key}.",
                        extraction_method=extraction_method,
                        source=provenance.source,
                        source_engine=provenance.source_engine,
                    )
                )
    return output


def _build_line_contexts(
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
) -> list[LineContext]:
    return [
        LineContext(line=line, tokens=tokens_for_line(line, spatial_text_map))
        for line in evidence_lines
    ]


def _match_label_prefix(line_text: str) -> tuple[str, str | None] | None:
    stripped = line_text.strip()
    if not stripped:
        return None
    for key in _sorted_label_keys():
        pattern = rf"^\s*{re.escape(key)}\s*(?::|-)?\s*(.*)$"
        match = re.match(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip() or None
        return key, value
    return None


def _sorted_label_keys() -> list[str]:
    return sorted(LABEL_CONFIG.keys(), key=len, reverse=True)


def _build_local_provenance(
    *,
    line_context: LineContext,
    label_text: str,
    value_text: str,
    provenance_method: str,
    base_confidence: float,
    context_snippet: str | None = None,
    additional_context_box: BoundingBox | None = None,
) -> CandidateProvenance | None:
    line_tokens = line_context.tokens
    value_boxes, match_confidence, match_type = ground_value_to_spatial_map(value_text, line_tokens)
    value_box = value_boxes[0] if value_boxes else None
    if value_box is None and line_context.line.bbox is None:
        return None

    label_boxes, _, _ = ground_value_to_spatial_map(label_text, line_tokens)
    label_box = label_boxes[0] if label_boxes else None
    primary_box = value_box or line_context.line.bbox
    context_box = merge_bounding_boxes([label_box, value_box, line_context.line.bbox, additional_context_box])
    token_confidence = average_token_confidence(line_tokens, bounding_box=primary_box)
    source_engine = resolve_source_type(line_tokens)
    provenance_confidence = _combine_confidence(
        base_confidence,
        match_confidence,
        token_confidence,
    )
    evidence_snippet = context_snippet or _compose_evidence_snippet(label_text, value_text)
    return CandidateProvenance(
        source_text=value_text.strip(),
        evidence_snippet=evidence_snippet,
        page=primary_box.page if primary_box is not None else line_context.line.page,
        bounding_box=primary_box,
        context_bounding_box=context_box,
        confidence=provenance_confidence,
        grounding_match_type=f"{provenance_method}_{match_type if match_type != 'none' else 'line'}",
        provenance_method=provenance_method,
        provenance_confidence=provenance_confidence,
        source=source_engine,
        source_engine=source_engine,
    )


def _find_neighboring_value_provenance(
    *,
    line_contexts: Sequence[LineContext],
    line_index: int,
    label_text: str,
    category: str,
    family_hints: Sequence[str],
) -> CandidateProvenance | None:
    current = line_contexts[line_index]
    right_candidate = _find_right_neighbor(line_contexts, line_index)
    if right_candidate is not None:
        value_text = right_candidate.line.text.strip()
        if _value_matches_category(value_text, category, family_hints):
            return _build_local_provenance(
                line_context=right_candidate,
                label_text=label_text,
                value_text=value_text,
                provenance_method="nearby_right",
                base_confidence=NEARBY_RIGHT_BASE_CONFIDENCE,
                context_snippet=_compose_evidence_snippet(label_text, value_text),
                additional_context_box=current.line.bbox,
            )

    below_candidate = _find_below_neighbor(line_contexts, line_index)
    if below_candidate is None:
        return None
    value_text = below_candidate.line.text.strip()
    if not _value_matches_category(value_text, category, family_hints):
        return None
    return _build_local_provenance(
        line_context=below_candidate,
        label_text=label_text,
        value_text=value_text,
        provenance_method="nearby_below",
        base_confidence=NEARBY_BELOW_BASE_CONFIDENCE,
        context_snippet=_compose_evidence_snippet(label_text, value_text),
        additional_context_box=current.line.bbox,
    )


def _find_right_neighbor(line_contexts: Sequence[LineContext], line_index: int) -> LineContext | None:
    current = line_contexts[line_index]
    for candidate in line_contexts[line_index + 1 :]:
        if candidate.line.page != current.line.page:
            break
        if abs(candidate.line.bbox.y0 - current.line.bbox.y0) > 6.0:
            if candidate.line.bbox.y0 > current.line.bbox.y1:
                break
            continue
        if candidate.line.bbox.x0 >= current.line.bbox.x1 and (candidate.line.bbox.x0 - current.line.bbox.x1) <= NEIGHBOR_HORIZONTAL_GAP:
            if _match_label_prefix(candidate.line.text) is None:
                return candidate
    return None


def _find_below_neighbor(line_contexts: Sequence[LineContext], line_index: int) -> LineContext | None:
    current = line_contexts[line_index]
    for candidate in line_contexts[line_index + 1 :]:
        if candidate.line.page != current.line.page:
            break
        if _match_label_prefix(candidate.line.text) is not None:
            break
        vertical_gap = candidate.line.bbox.y0 - current.line.bbox.y1
        if vertical_gap < 0:
            continue
        if vertical_gap > NEIGHBOR_VERTICAL_GAP:
            break
        if candidate.line.bbox.x0 <= current.line.bbox.x1 + NEIGHBOR_HORIZONTAL_GAP:
            return candidate
    return None


def _resolve_semantic_assignment(
    *,
    raw_label: str,
    base_category: str,
    value_text: str,
    line_contexts: Sequence[LineContext],
    line_index: int,
    family_hints: Sequence[str],
) -> tuple[str, str, bool | None]:
    current = line_contexts[line_index]
    previous = line_contexts[line_index - 1] if line_index > 0 and line_contexts[line_index - 1].line.page == current.line.page else None
    current_lower = current.line.text.lower()
    use_previous_context = previous is not None and _normalized_text(current.line.text) == _normalized_text(value_text)
    previous_lower = previous.line.text.lower() if use_previous_context and previous is not None else ""
    label_lower = raw_label.strip().lower()
    family_text = " ".join(family_hints)
    compact_value = re.sub(r"[^A-Za-z0-9]", "", value_text.strip()).upper()
    digits_only = re.sub(r"\D", "", value_text)

    if base_category == "person_name":
        if _contains_any(current_lower, ("father", "mother", "guardian", "parent", "spouse")) or _contains_any(label_lower, ("father", "mother", "guardian", "parent", "spouse")):
            return "guardian_name", "person_name", True
        if _contains_any(current_lower, ("student", "candidate")) or _contains_any(label_lower, ("student", "name of student")):
            return "student_name", "person_name", True
        if _is_academic_family(family_hints) and label_lower in {"name", "candidate name"}:
            return "student_name", "person_name", True
        if _contains_any(label_lower, ("holder", "full", "applicant")) or _is_identity_family(family_hints):
            return "full_name", "person_name", True
        return "name", "person_name", True

    if base_category == "issuer":
        if "board" in label_lower or "board" in current_lower:
            return "board_name", "issuer", False
        if _contains_any(label_lower, ("institution", "school", "college", "university", "institute")) or _is_academic_family(family_hints):
            return "institution_name", "issuer", False
        return "issuer", "issuer", False

    if base_category == "registration_number":
        if "seat" in label_lower or "seat" in current_lower:
            return "seat_number", "registration_number", False
        if _contains_any(label_lower, ("registration", "register")) or _contains_any(current_lower, ("registration", "register")):
            return "registration_number", "registration_number", False
        if _contains_any(label_lower, ("roll",)) or _contains_any(current_lower, ("roll",)) or _is_academic_family(family_hints):
            return "roll_number", "registration_number", False
        return "registration_number", "registration_number", False

    if base_category == "document_number":
        if PAN_NUMBER_PATTERN.match(compact_value):
            return "pan_number", "tax_identifier", True
        if AADHAAR_NUMBER_PATTERN.match(digits_only) and (_is_aadhaar_family(family_hints) or _contains_any(f"{current_lower} {previous_lower}", ("aadhaar", "uid"))):
            return "aadhaar_number", "national_identifier", True
        if _contains_any(label_lower, ("passport",)):
            return "passport_number", "document_number", True
        if _contains_any(label_lower, ("license", "licence")):
            return "license_number", "license_number", False
        if _contains_any(current_lower, ("roll", "seat", "registration", "register")) or _is_academic_family(family_hints):
            if "seat" in current_lower:
                return "seat_number", "registration_number", False
            if _contains_any(current_lower, ("registration", "register")):
                return "registration_number", "registration_number", False
            return "roll_number", "registration_number", False
        return "document_number", "document_number", False

    if base_category == "license_number":
        return "license_number", "license_number", False

    if base_category == "tax_identifier":
        if PAN_NUMBER_PATTERN.match(compact_value) or "pan" in family_text or _contains_any(f"{current_lower} {previous_lower}", ("pan", "permanent account number")):
            return "pan_number", "tax_identifier", True
        return "tax_identifier", "tax_identifier", True

    if base_category == "national_identifier":
        if PAN_NUMBER_PATTERN.match(compact_value) or _is_pan_family(family_hints) or _contains_any(f"{current_lower} {previous_lower}", ("pan", "permanent account number")):
            return "pan_number", "tax_identifier", True
        if AADHAAR_NUMBER_PATTERN.match(digits_only) and (_is_aadhaar_family(family_hints) or _contains_any(f"{current_lower} {previous_lower}", ("aadhaar", "uidai", "uid"))):
            return "aadhaar_number", "national_identifier", True
        return "government_identifier", "national_identifier", True

    if base_category == "score":
        if RESULT_STATUS_PATTERN.search(current_lower) or RESULT_STATUS_PATTERN.fullmatch(value_text.strip()):
            return "result_status", "score", False
        if "grade" in label_lower or GRADE_VALUE_PATTERN.match(value_text.strip()):
            return "grade", "score", False
        if _contains_any(current_lower, ("marks", "score", "cgpa", "gpa", "percentage")) or PERCENT_PATTERN.search(value_text):
            return "marks", "score", False
        return "score", "score", False

    if base_category == "date_of_birth":
        return "date_of_birth", "date_of_birth", True

    if base_category == "issue_date":
        return "issue_date", "issue_date", False

    if base_category == "expiry_date":
        return "expiry_date", "expiry_date", False

    if base_category == "date_reference":
        line_haystack = f"{label_lower} {current_lower} {previous_lower}"
        if _contains_any(line_haystack, ("dob", "date of birth", "birth date", "year of birth", "yob")):
            return "date_of_birth", "date_of_birth", True
        if "issue date" in line_haystack:
            return "issue_date", "issue_date", False
        if "expiry date" in line_haystack or _contains_any(line_haystack, ("valid until", "valid till", "expiry")):
            return "expiry_date", "expiry_date", False
        if _is_academic_family(family_hints) and _contains_any(line_haystack, ("exam", "result", "year of passing", "exam year", "passing year")):
            return "exam_year", "date_reference", False
        return "date", "date_reference", False

    return _default_semantic_label(base_category, raw_label), base_category, None


def _resolve_pattern_context(
    *,
    default_label: str,
    default_category: str,
    line_contexts: Sequence[LineContext],
    line_index: int,
    value: str,
    family_hints: Sequence[str],
) -> dict[str, object] | None:
    current = line_contexts[line_index]
    line_text = current.line.text
    line_lower = line_text.lower()
    previous = line_contexts[line_index - 1] if line_index > 0 and line_contexts[line_index - 1].line.page == current.line.page else None
    context_label = None
    if previous is not None and _normalized_text(current.line.text) == _normalized_text(value):
        label_binding = _match_label_prefix(previous.line.text)
        if label_binding is not None:
            context_label = label_binding[0]

    effective_label = context_label or default_label
    semantic_label, semantic_category, semantic_is_pii = _resolve_semantic_assignment(
        raw_label=effective_label,
        base_category=default_category,
        value_text=value,
        line_contexts=line_contexts,
        line_index=line_index,
        family_hints=family_hints,
    )

    if default_label == "year" and semantic_label == "date":
        return None
    if default_label == "result" and semantic_label == "score":
        return None

    context_display = _display_label_for_semantic_label(semantic_label)
    if semantic_label == "date":
        context_display = None
    if semantic_label == "document_number":
        context_display = "Document Number"

    return {
        "label": semantic_label,
        "category": semantic_category,
        "is_pii": semantic_is_pii,
        "context_label": context_display,
    }


def _build_pattern_provenance(
    *,
    line_contexts: Sequence[LineContext],
    line_index: int,
    value_text: str,
    label_text: str | None,
    contextualized: bool,
) -> CandidateProvenance | None:
    current = line_contexts[line_index]
    if label_text:
        return _build_local_provenance(
            line_context=current,
            label_text=label_text,
            value_text=value_text,
            provenance_method="pattern_contextual",
            base_confidence=LOCAL_PATTERN_BASE_CONFIDENCE + CONTEXTUAL_PATTERN_BOOST,
        )

    line_tokens = current.tokens
    boxes, match_confidence, match_type = ground_value_to_spatial_map(value_text, line_tokens or current.tokens)
    value_box = boxes[0] if boxes else current.line.bbox
    token_confidence = average_token_confidence(line_tokens, bounding_box=value_box)
    source_engine = resolve_source_type(line_tokens)
    combined_confidence = _combine_confidence(
        LOCAL_PATTERN_BASE_CONFIDENCE if contextualized else GLOBAL_PATTERN_BASE_CONFIDENCE,
        match_confidence,
        token_confidence,
    )
    if value_box is None:
        return None
    return CandidateProvenance(
        source_text=value_text.strip(),
        evidence_snippet=value_text.strip(),
        page=value_box.page,
        bounding_box=value_box,
        context_bounding_box=current.line.bbox,
        confidence=combined_confidence,
        grounding_match_type=f"pattern_{match_type if match_type != 'none' else 'line'}",
        provenance_method="pattern_local",
        provenance_confidence=combined_confidence,
        source=source_engine,
        source_engine=source_engine,
    )


def _value_matches_category(value_text: str, category: str, family_hints: Sequence[str]) -> bool:
    cleaned = value_text.strip()
    compact = re.sub(r"[^A-Za-z0-9]", "", cleaned).upper()
    if category == "person_name":
        return bool(NAME_PATTERN.match(cleaned)) and len(cleaned.split()) >= 2
    if category == "date_of_birth":
        return bool(DATE_PATTERN.search(cleaned))
    if category == "registration_number":
        return bool(re.match(r"^[A-Z0-9-]{5,24}$", compact))
    if category == "national_identifier":
        digits = re.sub(r"\D", "", cleaned)
        return len(digits) == 12
    if category == "tax_identifier":
        return bool(re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", compact))
    if category in {"document_number", "license_number"}:
        return bool(re.match(r"^[A-Z0-9-]{5,24}$", compact))
    if category == "score":
        return bool(re.match(r"^(?:[A-F][+-]?|\d{1,3}(?:\.\d+)?%?|CGPA\s*[-:]?\s*\d+(?:\.\d+)?/?10)$", cleaned, flags=re.IGNORECASE))
    if category == "issuer":
        return any(character.isalpha() for character in cleaned)
    if category in {"issue_date", "expiry_date", "date_reference"}:
        return bool(DATE_PATTERN.search(cleaned))
    return bool(cleaned)


def _compose_evidence_snippet(label_text: str, value_text: str) -> str:
    return f"{_display_label_text(label_text)}: {value_text.strip()}".strip()


def _display_label_text(label_text: str) -> str:
    normalized = label_text.strip().lower()
    if normalized == "dob":
        return "DOB"
    if normalized == "pan":
        return "PAN"
    if normalized == "pan number":
        return "PAN Number"
    if normalized == "aadhaar":
        return "Aadhaar"
    if normalized == "aadhaar number":
        return "Aadhaar Number"
    return label_text.strip().title()


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _combine_confidence(base_confidence: float, match_confidence: float, token_confidence: float) -> float:
    effective_match = match_confidence or MIN_ACCEPTED_CONFIDENCE
    effective_token = token_confidence or 1.0
    return round(min(0.995, (base_confidence * 0.6) + (effective_match * 0.25) + (effective_token * 0.15)), 4)


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
    scores: dict[str, float] = defaultdict(float)

    def bump(hint: str, score: float) -> None:
        scores[hint] += score

    if _contains_any(lowered, ("aadhaar", "uidai", "unique identification authority", "government of india")):
        bump("aadhaar_card", 3.0)
    if GOV_ID_PATTERN.search(raw_text) and re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", raw_text):
        bump("aadhaar_card", 2.0)
    if _contains_any(lowered, ("dob", "date of birth", "year of birth", "yob")):
        bump("identity_document", 0.75)

    if _contains_any(lowered, ("permanent account number", "income tax department", "pan card", "pan no", "pan number")):
        bump("pan_card", 3.0)
    if PAN_NUMBER_PATTERN.search(re.sub(r"[^A-Za-z0-9]", "", raw_text.upper())):
        bump("pan_card", 2.0)

    if _contains_any(lowered, ("report card", "grade report", "progress report")):
        bump("report_card", 3.0)
    if _contains_any(lowered, ("marksheet", "mark sheet", "statement of marks")):
        bump("marksheet", 3.0)
    if _contains_any(lowered, ("cgpa", "semester", "transcript")):
        bump("transcript", 3.0)

    if _contains_any(lowered, ("roll number", "roll no", "seat number", "seat no", "student name", "marks", "grade", "result", "board", "school", "exam")):
        bump("academic_record", 1.5)
    if _contains_any(lowered, ("passport", "licence", "license", "holder name", "applicant name", "address", "issue date", "expiry date")):
        bump("identity_document", 1.5)
    if _contains_any(lowered, ("certificate", "course completion")):
        bump("certificate", 2.0)
    if _contains_any(lowered, ("tax", "invoice", "balance", "account", "amount")):
        bump("financial_document", 1.5)

    if scores.get("aadhaar_card"):
        bump("identity_document", 1.0)
    if scores.get("pan_card"):
        bump("identity_document", 1.0)
    if any(scores.get(hint) for hint in ("report_card", "marksheet", "transcript")):
        bump("academic_record", 1.0)

    ordered = [hint for hint, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])) if score >= 1.0]
    return ordered or ["generic_pdf_evidence"]


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
    if "aadhaar" in lowered or re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", raw_text):
        categories.append("aadhaar_number")
    if "pan" in lowered or PAN_NUMBER_PATTERN.search(re.sub(r"[^A-Za-z0-9]", "", raw_text.upper())):
        categories.append("pan_number")
    if "passport" in lowered:
        categories.append("document_number")
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
    for key in _sorted_label_keys():
        value = LABEL_CONFIG[key]
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
        if YEAR_PATTERN.fullmatch(cleaned):
            return cleaned
        parsed = _try_parse_date(cleaned)
        return parsed or cleaned
    return cleaned


def _try_parse_date(value: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%b %Y", "%B %Y", "%Y"):
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


def _default_semantic_label(category: str, raw_label: str) -> str:
    return CANONICAL_LABELS.get(category, _slug(raw_label))


def _display_label_for_semantic_label(label: str) -> str:
    display_map = {
        "full_name": "Full Name",
        "student_name": "Student Name",
        "guardian_name": "Guardian Name",
        "aadhaar_number": "Aadhaar Number",
        "pan_number": "PAN Number",
        "document_number": "Document Number",
        "passport_number": "Passport Number",
        "license_number": "License Number",
        "roll_number": "Roll Number",
        "seat_number": "Seat Number",
        "registration_number": "Registration Number",
        "institution_name": "Institution Name",
        "board_name": "Board Name",
        "exam_year": "Exam Year",
        "result_status": "Result Status",
    }
    return display_map.get(label, label.replace("_", " ").title())


def _contains_any(value: str, needles: Sequence[str]) -> bool:
    return any(needle in value for needle in needles)


def _is_aadhaar_family(family_hints: Sequence[str]) -> bool:
    return "aadhaar_card" in family_hints


def _is_pan_family(family_hints: Sequence[str]) -> bool:
    return "pan_card" in family_hints


def _is_identity_family(family_hints: Sequence[str]) -> bool:
    return any(hint in family_hints for hint in ("aadhaar_card", "pan_card", "identity_document"))


def _is_academic_family(family_hints: Sequence[str]) -> bool:
    return any(hint in family_hints for hint in ("report_card", "marksheet", "transcript", "academic_record"))


def _is_section_header(text: str) -> bool:
    normalized = text.lower().strip().strip(":")
    return normalized in {"education", "experience", "skills", "report card", "marksheet", "student details", "academic details"} or (text.isupper() and len(text.split()) <= 5)


def _looks_like_table_row(text: str) -> bool:
    cells = [part for part in re.split(r"\s{2,}|\t", text) if part]
    numeric_cells = sum(1 for cell in cells if any(char.isdigit() for char in cell))
    return len(cells) >= 3 and numeric_cells >= 2
