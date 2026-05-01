from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from extraction.layout_analyzer import build_evidence_lines
from extraction.models import BoundingBox, SpatialTextToken


DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
AADHAAR_PATTERN = re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")
PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
ROLL_PATTERN = re.compile(r"\b[A-Z]{2,}\d{4,}\b")
YEAR_PATTERN = re.compile(r"\b20\d{2}\b")


class LegacyFieldCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    candidate_id: str
    label: str
    category: str
    raw_value: str
    normalized_value: str
    source_text: str
    evidence_snippet: str
    page: int
    confidence: float
    bounding_box: BoundingBox
    context_bounding_box: BoundingBox
    provenance_method: str
    source_engine: str
    is_pii: bool = False
    requires_verification: bool = True
    verification_reason: str = "General verification"
    extraction_method: str = "native_text"


def extract_field_candidates(
    raw_text: str,
    evidence_lines,
    spatial_text_map,
    extraction_method: str,
    warnings,
):
    del warnings
    candidates: list[LegacyFieldCandidate] = []
    seen: set[tuple[str, str, int]] = set()
    line_tokens = [
        [token for token in spatial_text_map if token.page == line.page and token in _tokens_for_bbox(spatial_text_map, line.bbox)]
        for line in evidence_lines
    ]

    for index, line in enumerate(evidence_lines):
        binding = _extract_binding(line.text, evidence_lines, index)
        if binding is None:
            continue
        label, value, provenance_method = binding
        if not value:
            continue
        semantic_label, category, pii = _classify(label, value, raw_text)
        if not semantic_label:
            continue

        if provenance_method == "nearby_below" and index + 1 < len(evidence_lines):
            value_line = evidence_lines[index + 1]
            value_tokens = _tokens_for_bbox(spatial_text_map, value_line.bbox)
            value_box = value_line.bbox
            context_box = line.bbox
            source_engine = _source_engine(value_tokens)
            evidence_snippet = f"{line.text.strip()}\n{value_line.text.strip()}"
        else:
            value_tokens = _value_tokens_for_line(line, spatial_text_map, value)
            value_box = _merge_token_box(value_tokens) or line.bbox
            context_box = line.bbox
            source_engine = _source_engine(value_tokens or _tokens_for_bbox(spatial_text_map, line.bbox))
            evidence_snippet = line.text.strip()

        candidate = LegacyFieldCandidate(
            candidate_id=f"{line.page}:{semantic_label}:{value}",
            label=semantic_label,
            category=category,
            raw_value=value,
            normalized_value=value,
            source_text=value,
            evidence_snippet=evidence_snippet,
            page=line.page,
            confidence=0.96 if provenance_method == "same_line" else 0.82,
            bounding_box=value_box,
            context_bounding_box=context_box,
            provenance_method=provenance_method,
            source_engine=source_engine,
            is_pii=pii,
            requires_verification=True,
            verification_reason=_verification_reason(category),
            extraction_method=extraction_method,
        )
        _append_candidate(candidates, seen, candidate)

    _add_pattern_candidates(candidates, seen, evidence_lines, spatial_text_map, extraction_method, raw_text)
    return candidates


def build_generalized_analysis(raw_text, spatial_text_map, extraction_method, warnings):
    evidence_lines = build_evidence_lines(spatial_text_map)
    field_candidates = extract_field_candidates(raw_text, evidence_lines, spatial_text_map, extraction_method, warnings)
    return evidence_lines, field_candidates


def _extract_binding(text: str, evidence_lines, index: int) -> tuple[str, str, str] | None:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return None
    if ":" in normalized:
        left, right = normalized.split(":", 1)
        return left.strip(), right.strip(), "same_line"
    if index + 1 < len(evidence_lines) and evidence_lines[index + 1].page == evidence_lines[index].page:
        lower = normalized.lower()
        if lower in {"date of birth", "dob", "holder name", "student name", "full name"}:
            return normalized, evidence_lines[index + 1].text.strip(), "nearby_below"
    parts = normalized.split()
    if len(parts) >= 3 and parts[0].lower() == "reference" and parts[1].lower() == "id":
        return "Reference ID", " ".join(parts[2:]), "same_line"
    if len(parts) >= 2 and parts[0].lower() == "date":
        return "Date", " ".join(parts[1:]), "same_line"
    return None


def _classify(label: str, value: str, raw_text: str) -> tuple[str | None, str | None, bool]:
    normalized = label.strip().lower()
    raw_lower = raw_text.lower()

    if normalized in {"holder name", "full name"}:
        return "full_name", "person_name", True
    if normalized == "student name":
        return "student_name", "person_name", True
    if normalized in {"date of birth", "dob"}:
        return "date_of_birth", "date_of_birth", False
    if normalized == "issue date":
        return "issue_date", "issue_date", False
    if normalized in {"aadhaar number", "aadhaar"} or AADHAAR_PATTERN.fullmatch(value):
        return "aadhaar_number", "national_identifier", True
    if normalized in {"pan", "pan number"} or PAN_PATTERN.fullmatch(value):
        return "pan_number", "tax_identifier", True
    if normalized in {"roll no", "roll number"}:
        return "roll_number", "registration_number", False
    if normalized in {"registration no", "registration number"}:
        return "registration_number", "registration_number", False
    if normalized == "board name":
        return "board_name", "institution_name", False
    if normalized == "school name":
        return "institution_name", "institution_name", False
    if normalized == "exam year":
        return "exam_year", "exam_year", False
    if normalized == "grade":
        return "grade", "score", False
    if normalized == "result":
        return "result_status", "score", False
    if normalized in {"reference id", "document id", "id"}:
        return "document_number", "document_number", False
    if normalized == "date":
        if "date of birth" in raw_lower or "dob" in raw_lower:
            return None, None, False
        return "date", "date_reference", False
    return None, None, False


def _add_pattern_candidates(candidates, seen, evidence_lines, spatial_text_map, extraction_method: str, raw_text: str) -> None:
    raw_lower = raw_text.lower()
    for line in evidence_lines:
        date_matches = DATE_PATTERN.findall(line.text)
        for match in date_matches:
            if "dob" in line.text.lower() or "date of birth" in line.text.lower():
                label, category = "date_of_birth", "date_of_birth"
                confidence = 0.95
            elif "issue" in line.text.lower():
                label, category = "issue_date", "issue_date"
                confidence = 0.9
            else:
                label, category = "date", "date_reference"
                confidence = 0.68
            value_tokens = _value_tokens_for_line(line, spatial_text_map, match)
            box = _merge_token_box(value_tokens) or line.bbox
            candidate = LegacyFieldCandidate(
                candidate_id=f"{line.page}:{label}:{match}",
                label=label,
                category=category,
                raw_value=match,
                normalized_value=match,
                source_text=match,
                evidence_snippet=line.text.strip(),
                page=line.page,
                confidence=confidence,
                bounding_box=box,
                context_bounding_box=line.bbox,
                provenance_method="same_line" if line.text.strip() != match else "pattern_only",
                source_engine=_source_engine(value_tokens or _tokens_for_bbox(spatial_text_map, line.bbox)),
                extraction_method=extraction_method,
            )
            _append_candidate(candidates, seen, candidate)

        for match in AADHAAR_PATTERN.findall(line.text):
            value_tokens = _value_tokens_for_line(line, spatial_text_map, match)
            box = _merge_token_box(value_tokens) or line.bbox
            candidate = LegacyFieldCandidate(
                candidate_id=f"{line.page}:aadhaar:{match}",
                label="aadhaar_number",
                category="national_identifier",
                raw_value=match,
                normalized_value=match,
                source_text=match,
                evidence_snippet=line.text.strip(),
                page=line.page,
                confidence=0.95,
                bounding_box=box,
                context_bounding_box=line.bbox,
                provenance_method="same_line",
                source_engine=_source_engine(value_tokens or _tokens_for_bbox(spatial_text_map, line.bbox)),
                is_pii=True,
                extraction_method=extraction_method,
            )
            _append_candidate(candidates, seen, candidate)

        for match in PAN_PATTERN.findall(line.text):
            value_tokens = _value_tokens_for_line(line, spatial_text_map, match)
            box = _merge_token_box(value_tokens) or line.bbox
            candidate = LegacyFieldCandidate(
                candidate_id=f"{line.page}:pan:{match}",
                label="pan_number",
                category="tax_identifier",
                raw_value=match,
                normalized_value=match,
                source_text=match,
                evidence_snippet=line.text.strip(),
                page=line.page,
                confidence=0.94,
                bounding_box=box,
                context_bounding_box=line.bbox,
                provenance_method="same_line",
                source_engine=_source_engine(value_tokens or _tokens_for_bbox(spatial_text_map, line.bbox)),
                is_pii=True,
                extraction_method=extraction_method,
            )
            _append_candidate(candidates, seen, candidate)

        if "reference id" in line.text.lower():
            match = ROLL_PATTERN.search(line.text)
            if match:
                value = match.group(0)
                value_tokens = _value_tokens_for_line(line, spatial_text_map, value)
                box = _merge_token_box(value_tokens) or line.bbox
                candidate = LegacyFieldCandidate(
                    candidate_id=f"{line.page}:document:{value}",
                    label="document_number",
                    category="document_number",
                    raw_value=value,
                    normalized_value=value,
                    source_text=value,
                    evidence_snippet=line.text.strip(),
                    page=line.page,
                    confidence=0.73,
                    bounding_box=box,
                    context_bounding_box=line.bbox,
                    provenance_method="same_line",
                    source_engine=_source_engine(value_tokens or _tokens_for_bbox(spatial_text_map, line.bbox)),
                    extraction_method=extraction_method,
                )
                _append_candidate(candidates, seen, candidate)

        if "exam year" in raw_lower and YEAR_PATTERN.search(line.text):
            value = YEAR_PATTERN.search(line.text).group(0)
            value_tokens = _value_tokens_for_line(line, spatial_text_map, value)
            box = _merge_token_box(value_tokens) or line.bbox
            candidate = LegacyFieldCandidate(
                candidate_id=f"{line.page}:exam-year:{value}",
                label="exam_year",
                category="exam_year",
                raw_value=value,
                normalized_value=value,
                source_text=value,
                evidence_snippet=line.text.strip(),
                page=line.page,
                confidence=0.8,
                bounding_box=box,
                context_bounding_box=line.bbox,
                provenance_method="same_line",
                source_engine=_source_engine(value_tokens or _tokens_for_bbox(spatial_text_map, line.bbox)),
                extraction_method=extraction_method,
            )
            _append_candidate(candidates, seen, candidate)


def _tokens_for_bbox(spatial_text_map: list[SpatialTextToken], bbox: BoundingBox) -> list[SpatialTextToken]:
    matches = []
    for token in spatial_text_map:
        if token.page != bbox.page:
            continue
        x0, y0, x1, y1 = [float(value) for value in token.bbox]
        if x0 >= bbox.x0 - 1 and x1 <= bbox.x1 + 1 and y0 >= bbox.y0 - 1 and y1 <= bbox.y1 + 1:
            matches.append(token)
    return matches


def _value_tokens_for_line(line, spatial_text_map: list[SpatialTextToken], value: str) -> list[SpatialTextToken]:
    tokens = _tokens_for_bbox(spatial_text_map, line.bbox)
    if not value:
        return tokens
    wanted = value.split()
    matched = [token for token in tokens if any(piece.lower() == token.text.strip().lower().rstrip(":") for piece in wanted)]
    return matched or [token for token in tokens if token.text.strip().lower() in value.lower()]


def _merge_token_box(tokens: list[SpatialTextToken]) -> BoundingBox | None:
    if not tokens:
        return None
    x0 = min(float(token.bbox[0]) for token in tokens)
    y0 = min(float(token.bbox[1]) for token in tokens)
    x1 = max(float(token.bbox[2]) for token in tokens)
    y1 = max(float(token.bbox[3]) for token in tokens)
    return BoundingBox(page=tokens[0].page, x0=x0, y0=y0, x1=x1, y1=y1)


def _source_engine(tokens: list[SpatialTextToken]) -> str:
    if not tokens:
        return "native_text"
    source = tokens[0].source
    return source if source != "native_text" else "native_text"


def _verification_reason(category: str) -> str:
    if category in {"person_name", "national_identifier", "tax_identifier"}:
        return "Identity claim"
    if category == "registration_number":
        return "Academic identifier"
    return "General verification"


def _append_candidate(candidates, seen, candidate: LegacyFieldCandidate) -> None:
    key = (candidate.label, candidate.normalized_value, candidate.page)
    if key in seen:
        return
    seen.add(key)
    candidates.append(candidate)
