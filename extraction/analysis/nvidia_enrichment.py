from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from backend.app.inference import NvidiaChatClient, NvidiaInferenceError, load_nvidia_inference_config
from extraction.grounding.spatial_locator import MIN_ACCEPTED_CONFIDENCE, ground_value_to_spatial_map
from extraction.schema.models import (
    BoundingBox,
    EnrichmentMetadata,
    EvidenceLine,
    ExtractionWarning,
    FieldCandidate,
    SpatialTextToken,
)


PII_PROMPT = """
You are enriching a bounded document-extraction pipeline with conservative entity typing.

Return valid JSON only with this schema:
{
  "entities": [
    {
      "text": "exact span text copied from the provided fragments",
      "label": "one of PERSON_NAME, STUDENT_NAME, DATE_OF_BIRTH, PHONE_NUMBER, EMAIL, ADDRESS, AADHAAR_NUMBER, PAN_NUMBER, DOCUMENT_NUMBER, REGISTRATION_NUMBER, INSTITUTION_NAME, PROGRAM_NAME, SCORE_OR_GRADE, YEAR_REFERENCE",
      "confidence": 0.0
    }
  ]
}

Rules:
- Copy exact text spans from the provided fragments only.
- Do not invent text, values, geometry, or trust outcomes.
- Prefer returning fewer entities over low-confidence guesses.
- If you are unsure, omit the entity.
""".strip()


_ENTITY_SPECS = {
    "person_name": ("name", "person_name", True),
    "student_name": ("student_name", "person_name", True),
    "date_of_birth": ("date_of_birth", "date_of_birth", True),
    "phone_number": ("phone_number", "phone_number", True),
    "email": ("email", "email", True),
    "address": ("address", "address", True),
    "aadhaar_number": ("aadhaar", "national_identifier", True),
    "pan_number": ("pan", "tax_identifier", True),
    "document_number": ("document_id", "document_number", True),
    "registration_number": ("registration_number", "registration_number", False),
    "institution_name": ("institution", "issuer", False),
    "program_name": ("program_name", "program_name", False),
    "score_or_grade": ("score", "score", False),
    "year_reference": ("year", "date_reference", False),
}


def enrich_field_candidates_with_nvidia(
    *,
    raw_text: str,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
    warnings: list[ExtractionWarning],
    base_candidates: Sequence[FieldCandidate],
) -> tuple[list[FieldCandidate], EnrichmentMetadata]:
    config = load_nvidia_inference_config()
    metadata = EnrichmentMetadata(
        pii_enrichment_used=False,
        pii_provider="nvidia" if config.pii_enrichment_enabled else None,
        pii_model_used=config.pii_model if config.pii_enrichment_enabled else None,
        fallback_used=False,
        warning_codes=[],
    )
    if not config.pii_enrichment_enabled:
        return list(base_candidates), metadata
    if not raw_text.strip() or not evidence_lines:
        return list(base_candidates), metadata

    client = NvidiaChatClient(config)
    available, reason = client.is_configured()
    if not available:
        metadata.fallback_used = True
        metadata.warning_codes.append("NVIDIA_PII_NOT_CONFIGURED")
        return list(base_candidates), metadata

    try:
        payload = client.chat_json(
            model=config.pii_model,
            system_prompt=PII_PROMPT,
            user_payload=_build_gliner_payload(raw_text, evidence_lines, max_chars=config.max_input_chars),
            timeout_ms=config.timeout_ms,
            retry_budget=config.retry_budget,
        )
    except NvidiaInferenceError as exc:
        warnings.append(
            ExtractionWarning(
                code="NVIDIA_PII_ENRICHMENT_FAILED",
                message=f"NVIDIA GLiNER PII enrichment failed and deterministic extraction was retained: {exc}",
            )
        )
        metadata.fallback_used = True
        metadata.warning_codes.append("NVIDIA_PII_ENRICHMENT_FAILED")
        return list(base_candidates), metadata

    enriched_candidates = _build_enriched_candidates(
        payload.get("entities"),
        evidence_lines=evidence_lines,
        spatial_text_map=spatial_text_map,
        extraction_method=extraction_method,
    )
    metadata.pii_enrichment_used = True
    if not enriched_candidates:
        metadata.warning_codes.append("NVIDIA_PII_NO_ENTITIES")
        return list(base_candidates), metadata
    merged = _merge_candidates(list(base_candidates), enriched_candidates)
    return merged, metadata


def _build_gliner_payload(raw_text: str, evidence_lines: Sequence[EvidenceLine], *, max_chars: int) -> dict[str, Any]:
    fragments: list[dict[str, Any]] = []
    total_chars = 0
    for line in evidence_lines[:40]:
        text = " ".join(line.text.split())
        if not text:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        clipped = text[:remaining]
        fragments.append({"page": line.page, "text": clipped})
        total_chars += len(clipped) + 1
    return {
        "task": "pii_field_candidate_enrichment",
        "raw_text_excerpt": raw_text[: min(len(raw_text), max_chars)],
        "evidence_fragments": fragments,
    }


def _build_enriched_candidates(
    entities: Any,
    *,
    evidence_lines: Sequence[EvidenceLine],
    spatial_text_map: Sequence[SpatialTextToken],
    extraction_method: str,
) -> list[FieldCandidate]:
    if not isinstance(entities, list):
        return []
    candidates: list[FieldCandidate] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        raw_value = str(item.get("text") or "").strip()
        if not raw_value:
            continue
        spec = _resolve_entity_spec(item.get("label"))
        if spec is None:
            continue
        label, category, is_pii = spec
        line = _find_evidence_line(raw_value, evidence_lines)
        if line is None:
            continue
        boxes, grounding_confidence, match_type = ground_value_to_spatial_map(raw_value, spatial_text_map)
        model_confidence = _coerce_float(item.get("confidence"), 0.65)
        if grounding_confidence < MIN_ACCEPTED_CONFIDENCE and line.bbox is None:
            continue
        confidence = round(min(max(model_confidence, MIN_ACCEPTED_CONFIDENCE), max(grounding_confidence, model_confidence)), 4)
        bounding_box = boxes[0] if boxes else line.bbox
        candidates.append(
            FieldCandidate(
                candidate_id=_candidate_id(label, raw_value, line.page),
                label=label,
                category=category,
                raw_value=raw_value,
                normalized_value=_normalize_value(raw_value, category),
                source_text=line.text,
                evidence_snippet=line.text,
                page=line.page,
                bounding_box=bounding_box,
                confidence=confidence,
                grounding_match_type=match_type if boxes else "line_match",
                is_pii=is_pii,
                requires_verification=True,
                verification_reason=f"NVIDIA GLiNER PII enrichment identified '{label}' as a bounded verification candidate.",
                extraction_method="nvidia_gliner_pii",
                source="nvidia_gliner_pii",
            )
        )
    return _dedupe_candidates(candidates)


def _merge_candidates(base_candidates: list[FieldCandidate], enriched_candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    merged = [candidate.model_copy(deep=True) for candidate in base_candidates]
    for enriched in enriched_candidates:
        match = _find_matching_candidate(merged, enriched)
        if match is None:
            merged.append(enriched)
            continue
        updates: dict[str, Any] = {
            "is_pii": match.is_pii or enriched.is_pii,
            "requires_verification": match.requires_verification or enriched.requires_verification,
        }
        if _should_refine_category(match.category, enriched.category):
            updates["category"] = enriched.category
            updates["verification_reason"] = enriched.verification_reason
        if _should_refine_label(match.label, enriched.label):
            updates["label"] = enriched.label
        if not match.verification_reason and enriched.verification_reason:
            updates["verification_reason"] = enriched.verification_reason
        if updates:
            merged[merged.index(match)] = match.model_copy(update=updates)
    return _dedupe_candidates(merged)


def _find_matching_candidate(candidates: Sequence[FieldCandidate], enriched: FieldCandidate) -> FieldCandidate | None:
    for candidate in candidates:
        if candidate.page != enriched.page:
            continue
        if candidate.normalized_value == enriched.normalized_value:
            return candidate
        candidate_text = _normalized_text(candidate.raw_value or candidate.source_text)
        enriched_text = _normalized_text(enriched.raw_value or enriched.source_text)
        if candidate_text and candidate_text == enriched_text:
            return candidate
    return None


def _find_evidence_line(value: str, evidence_lines: Sequence[EvidenceLine]) -> EvidenceLine | None:
    needle = _normalized_text(value)
    for line in evidence_lines:
        line_text = _normalized_text(line.text)
        if needle and needle in line_text:
            return line
    return None


def _resolve_entity_spec(label: Any) -> tuple[str, str, bool] | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(label or "").strip().lower()).strip("_")
    synonyms = {
        "person": "person_name",
        "name": "person_name",
        "full_name": "person_name",
        "student": "student_name",
        "student_name": "student_name",
        "dob": "date_of_birth",
        "birth_date": "date_of_birth",
        "date_of_birth": "date_of_birth",
        "phone": "phone_number",
        "mobile": "phone_number",
        "phone_number": "phone_number",
        "email_address": "email",
        "email": "email",
        "address": "address",
        "aadhaar": "aadhaar_number",
        "aadhaar_number": "aadhaar_number",
        "pan": "pan_number",
        "pan_number": "pan_number",
        "id_number": "document_number",
        "document_id": "document_number",
        "document_number": "document_number",
        "roll_number": "registration_number",
        "registration_number": "registration_number",
        "organisation": "institution_name",
        "organization": "institution_name",
        "school": "institution_name",
        "university": "institution_name",
        "institution_name": "institution_name",
        "degree": "program_name",
        "program_name": "program_name",
        "grade": "score_or_grade",
        "score": "score_or_grade",
        "score_or_grade": "score_or_grade",
        "year": "year_reference",
        "year_reference": "year_reference",
    }
    resolved = synonyms.get(normalized, normalized)
    return _ENTITY_SPECS.get(resolved)


def _normalize_value(value: str, category: str) -> str:
    cleaned = " ".join(str(value).strip().split())
    if category == "email":
        return cleaned.lower()
    if category == "phone_number":
        digits = re.sub(r"\D", "", cleaned)
        return digits[-10:] if len(digits) >= 10 else digits
    if category in {"document_number", "registration_number", "tax_identifier", "national_identifier"}:
        return cleaned.upper().replace(" ", "")
    return cleaned


def _normalized_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def _should_refine_category(current: str, enriched: str) -> bool:
    if current == enriched:
        return False
    if current in {"unknown", "document_number", "date_reference"} and enriched not in {"unknown", current}:
        return True
    if current == "issuer" and enriched == "person_name":
        return False
    return False


def _should_refine_label(current: str, enriched: str) -> bool:
    current_normalized = _normalized_text(current)
    enriched_normalized = _normalized_text(enriched)
    if current_normalized == enriched_normalized:
        return False
    return current_normalized in {"name", "document id", "document number", "year"} and bool(enriched_normalized)


def _candidate_id(label: str, value: str, page: int) -> str:
    return f"gliner_{hashlib.sha1(f'{label}|{value}|{page}'.encode('utf-8')).hexdigest()[:12]}"


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe_candidates(candidates: Sequence[FieldCandidate]) -> list[FieldCandidate]:
    grouped: dict[tuple[int, str, str], FieldCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: (-item.confidence, len(item.raw_value), item.label)):
        key = (candidate.page, candidate.category, candidate.normalized_value.lower())
        if key not in grouped:
            grouped[key] = candidate
    return sorted(grouped.values(), key=lambda item: (item.page, -item.confidence, item.label))
