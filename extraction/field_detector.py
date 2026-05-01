from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .grounder import average_token_confidence, ground_value_to_spatial_map, merge_bounding_boxes, tokens_for_line
from .llm_classifier import classify_candidate
from .models import BoundingBox, EvidenceLine, ExtractionSignals, FieldCandidate, SpatialTextToken
from .ner_extractor import extract_named_entities
from .table_extractor import extract_from_tables

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
AADHAAR_PATTERN = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
GENERIC_ID_PATTERN = re.compile(r"\b[A-Z0-9-]{5,24}\b")
SCORE_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?%?\b|\b[A-F][+-]?\b", re.IGNORECASE)
STRICT_SCORE_VALUE_PATTERN = re.compile(r"^\d{1,2}(?:\.\d+)?(?:/10|%)?$", re.IGNORECASE)
HEADER_ONLY_PATTERN = re.compile(r"^[A-Z][A-Z\s&/-]{2,}$")
RESUME_SECTION_HEADERS = {
    "summary",
    "academic projects",
    "technical competencies",
    "education",
    "extracurricular activities",
    "projects",
    "experience",
    "skills",
}
SKILL_LABELS = {
    "languages",
    "web technologies",
    "libraries & frameworks",
    "libraries and frameworks",
    "technology/languages used",
    "technical competencies",
    "core cs concepts",
    "information technology",
}
TECH_KEYWORDS = {
    "python",
    "java",
    "javascript",
    "django",
    "reactjs",
    "react",
    "numpy",
    "pandas",
    "matplotlib",
    "streamlit",
    "langchain",
    "docker",
    "opencv",
    "tensorflow",
    "keras",
    "html",
    "css",
    "deep learning",
    "data structures",
    "algorithms",
    "object oriented programming",
    "scikit-learn",
}

LABEL_MAP = {
    "name": ("Name", "personal_name"),
    "full name": ("Full Name", "personal_name"),
    "holder name": ("Holder Name", "personal_name"),
    "student name": ("Student Name", "personal_name"),
    "applicant name": ("Applicant Name", "personal_name"),
    "institution": ("Institution", "institution"),
    "institution name": ("Institution Name", "institution"),
    "issuer": ("Issuer", "institution"),
    "university": ("University", "institution"),
    "college": ("College", "institution"),
    "school": ("School", "institution"),
    "board": ("Board", "institution"),
    "board name": ("Board Name", "institution"),
    "degree": ("Degree", "credential_title"),
    "credential": ("Credential", "credential_title"),
    "certificate": ("Certificate", "credential_title"),
    "course": ("Course", "credential_title"),
    "program": ("Program", "credential_title"),
    "languages": ("Languages", "other"),
    "web technologies": ("Web Technologies", "other"),
    "libraries & frameworks": ("Libraries & Frameworks", "other"),
    "libraries and frameworks": ("Libraries & Frameworks", "other"),
    "technology/languages used": ("Technology/Languages Used", "other"),
    "technical competencies": ("Technical Competencies", "other"),
    "core cs concepts": ("Core CS Concepts", "other"),
    "cgpa": ("CGPA", "score"),
    "gpa": ("GPA", "score"),
    "marks": ("Marks", "score"),
    "grade": ("Grade", "score"),
    "score": ("Score", "score"),
    "percentage": ("Percentage", "score"),
    "result": ("Result", "score"),
    "date of birth": ("Date of Birth", "date"),
    "dob": ("DOB", "date"),
    "birth date": ("Birth Date", "date"),
    "issue date": ("Issue Date", "date"),
    "expiry date": ("Expiry Date", "date"),
    "valid till": ("Expiry Date", "date"),
    "valid until": ("Expiry Date", "date"),
    "roll number": ("Roll Number", "identifier"),
    "roll no": ("Roll Number", "identifier"),
    "registration number": ("Registration Number", "identifier"),
    "registration no": ("Registration Number", "identifier"),
    "seat number": ("Seat Number", "identifier"),
    "aadhaar number": ("Aadhaar Number", "identifier"),
    "pan number": ("PAN Number", "identifier"),
    "passport number": ("Passport Number", "identifier"),
    "license number": ("License Number", "identifier"),
    "email": ("Email", "contact"),
    "phone": ("Phone", "contact"),
    "mobile": ("Mobile", "contact"),
    "address": ("Address", "address"),
    "signature": ("Signature", "signature"),
    "seal": ("Seal", "seal"),
}


def extract_field_candidates(
    *,
    raw_text_per_page: dict[int, str],
    evidence_lines: list[EvidenceLine],
    spatial_text_map: list[SpatialTextToken],
    page_confidence: dict[int, float],
    page_methods: dict[int, str],
    tables_by_page: dict[int, list[list[list[str]]]],
    document_type_hint: str = "generic",
    llm_client=None,
) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    seen: set[tuple[str, str, int]] = set()
    tokens_by_page: dict[int, list[SpatialTextToken]] = defaultdict(list)
    for token in spatial_text_map:
        tokens_by_page[token.page].append(token)

    for index, line in enumerate(evidence_lines):
        line_tokens = tokens_for_line(line, spatial_text_map)
        label_candidate = _extract_label_value_candidate(
            line=line,
            line_tokens=line_tokens,
            evidence_lines=evidence_lines,
            line_index=index,
            page_confidence=page_confidence,
            page_methods=page_methods,
            document_type_hint=document_type_hint,
            llm_client=llm_client,
        )
        if label_candidate is not None and _allow_candidate(label_candidate, document_type_hint=document_type_hint) and _remember_candidate(seen, label_candidate):
            candidates.append(label_candidate)

        for pattern_candidate in _extract_pattern_candidates(
            line=line,
            line_tokens=line_tokens,
            page_tokens=tokens_by_page.get(line.page, []),
            page_confidence=page_confidence,
            page_methods=page_methods,
            document_type_hint=document_type_hint,
            llm_client=llm_client,
        ):
            if _allow_candidate(pattern_candidate, document_type_hint=document_type_hint) and _remember_candidate(seen, pattern_candidate):
                candidates.append(pattern_candidate)

    for entity in extract_named_entities(evidence_lines):
        candidate = _build_candidate(
            label=str(entity["label"]),
            raw_value=str(entity["value"]),
            category=str(entity["category"]),
            page=int(entity["page"]),
            page_tokens=tokens_by_page.get(int(entity["page"]), []),
            page_confidence=page_confidence,
            page_methods=page_methods,
            source_text=str(entity["value"]),
            detected_by=["ner"],
            regex_score=0.0,
            layout_score=0.45,
            ner_score=float(entity.get("score") or 0.65),
            semantic_score=0.65,
            document_type_hint=document_type_hint,
            llm_client=llm_client,
        )
        if _allow_candidate(candidate, document_type_hint=document_type_hint) and _remember_candidate(seen, candidate):
            candidates.append(candidate)

    for candidate in extract_from_tables(tables_by_page):
        grounded = _ground_candidate(candidate, tokens_by_page.get(candidate.page, []))
        if _allow_candidate(grounded, document_type_hint=document_type_hint) and _remember_candidate(seen, grounded):
            candidates.append(grounded)

    return candidates


def _extract_label_value_candidate(
    *,
    line: EvidenceLine,
    line_tokens: list[SpatialTextToken],
    evidence_lines: list[EvidenceLine],
    line_index: int,
    page_confidence: dict[int, float],
    page_methods: dict[int, str],
    document_type_hint: str,
    llm_client,
) -> FieldCandidate | None:
    binding = _split_label_value(line.text)
    if binding is None:
        return None
    raw_label, value = binding
    if not value and line_index + 1 < len(evidence_lines) and evidence_lines[line_index + 1].page == line.page:
        value = evidence_lines[line_index + 1].text.strip()
    if not value:
        return None
    friendly_label, category = _resolve_label(raw_label)
    source_text = f"{friendly_label}: {value}".strip()
    return _build_candidate(
        label=friendly_label,
        raw_value=value,
        category=category,
        page=line.page,
        page_tokens=line_tokens or [],
        page_confidence=page_confidence,
        page_methods=page_methods,
        source_text=source_text,
        detected_by=["regex", "layout"],
        regex_score=0.92,
        layout_score=0.88 if binding[1] else 0.68,
        ner_score=0.0,
        semantic_score=0.74,
        document_type_hint=document_type_hint,
        llm_client=llm_client,
    )


def _extract_pattern_candidates(
    *,
    line: EvidenceLine,
    line_tokens: list[SpatialTextToken],
    page_tokens: list[SpatialTextToken],
    page_confidence: dict[int, float],
    page_methods: dict[int, str],
    document_type_hint: str,
    llm_client,
) -> list[FieldCandidate]:
    specs = [
        ("Email", "contact", EMAIL_PATTERN),
        ("Phone", "contact", PHONE_PATTERN),
        ("Date", "date", DATE_PATTERN),
        ("Aadhaar Number", "identifier", AADHAAR_PATTERN),
        ("PAN Number", "identifier", PAN_PATTERN),
        ("Identifier", "identifier", GENERIC_ID_PATTERN),
        ("Score", "score", SCORE_PATTERN),
    ]
    output: list[FieldCandidate] = []
    for label, category, pattern in specs:
        for match in pattern.finditer(line.text):
            value = match.group(0).strip()
            if not value:
                continue
            if label == "Identifier" and value.upper() in {"PASS", "FAIL", "RESULT"}:
                continue
            if label == "Identifier" and not _looks_like_identifier_value(value, line.text):
                continue
            if label == "Score" and not _looks_like_score_value(value, line.text):
                continue
            candidate = _build_candidate(
                label=label,
                raw_value=value,
                category=category,
                page=line.page,
                page_tokens=page_tokens or line_tokens,
                page_confidence=page_confidence,
                page_methods=page_methods,
                source_text=line.text,
                detected_by=["regex"],
                regex_score=0.8,
                layout_score=0.42,
                ner_score=0.0,
                semantic_score=0.58,
                document_type_hint=document_type_hint,
                llm_client=llm_client,
            )
            output.append(candidate)
    return output


def _build_candidate(
    *,
    label: str,
    raw_value: str,
    category: str,
    page: int,
    page_tokens: list[SpatialTextToken],
    page_confidence: dict[int, float],
    page_methods: dict[int, str],
    source_text: str,
    detected_by: list[str],
    regex_score: float,
    layout_score: float,
    ner_score: float,
    semantic_score: float,
    document_type_hint: str,
    llm_client,
) -> FieldCandidate:
    llm_result = classify_candidate(label=label, value=raw_value, context=source_text, llm_client=llm_client)
    final_label = str(llm_result.get("label") or label)
    final_category = str(llm_result.get("category") or category)
    llm_score = float(llm_result.get("score") or 0.0)
    normalized_value = _normalize_value(raw_value, final_category)
    final_label = _clean_label(final_label)
    field_id = f"fld_{hashlib.sha1(f'{page}|{final_label}|{normalized_value}'.encode('utf-8')).hexdigest()[:12]}"
    candidate = FieldCandidate(
        field_id=field_id,
        label=final_label,
        raw_value=raw_value.strip(),
        normalized_value=normalized_value,
        category=final_category,  # type: ignore[arg-type]
        page=page,
        confidence=0.0,
        signals=ExtractionSignals(
            regex_score=regex_score,
            layout_score=layout_score,
            llm_score=llm_score,
            ner_score=ner_score,
            ocr_confidence=float(page_confidence.get(page) or 0.0),
            semantic_score=semantic_score,
            frequency=1,
        ),
        requires_verification=final_category not in {"other", "signature", "seal"},
        source_text=source_text[:120],
        extraction_method=_coerce_method(page_methods.get(page, "native")),  # type: ignore[arg-type]
        detected_by=[detector for detector in detected_by if detector in {"regex", "layout", "llm", "ner", "table"}],  # type: ignore[list-item]
    )
    if llm_score > 0:
        candidate.detected_by = list(dict.fromkeys([*candidate.detected_by, "llm"]))
    candidate = _retarget_resume_categories(candidate, document_type_hint=document_type_hint)
    return _ground_candidate(candidate, page_tokens)


def _ground_candidate(candidate: FieldCandidate, page_tokens: list[SpatialTextToken]) -> FieldCandidate:
    boxes, confidence, _ = ground_value_to_spatial_map(candidate.raw_value or "", page_tokens)
    if not boxes and candidate.source_text:
        boxes, confidence, _ = ground_value_to_spatial_map(candidate.source_text, page_tokens)
    if not boxes:
        return candidate
    token_confidence = average_token_confidence(page_tokens, bounding_box=merge_bounding_boxes(boxes))
    grounded = candidate.model_copy(
        update={
            "bounding_boxes": boxes,
            "signals": candidate.signals.model_copy(
                update={
                    "layout_score": max(candidate.signals.layout_score, confidence),
                    "ocr_confidence": max(candidate.signals.ocr_confidence, token_confidence),
                }
            ),
        }
    )
    return grounded


def _split_label_value(text: str) -> tuple[str, str] | None:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return None
    if ":" in normalized:
        left, right = normalized.split(":", 1)
        if left.strip() and len(left.strip().split()) <= 6:
            return left.strip(), right.strip()
    if " - " in normalized:
        left, right = normalized.split(" - ", 1)
        if left.strip() and len(left.strip().split()) <= 6:
            return left.strip(), right.strip()
    parts = normalized.split()
    if len(parts) >= 3:
        label_guess = " ".join(parts[:2]).lower()
        if label_guess in LABEL_MAP:
            return " ".join(parts[:2]), " ".join(parts[2:])
    return None


def _resolve_label(raw_label: str) -> tuple[str, str]:
    normalized = _normalize_label_key(raw_label)
    if normalized in LABEL_MAP:
        return LABEL_MAP[normalized]
    for key, value in LABEL_MAP.items():
        if normalized.startswith(key):
            return value
    return _clean_label(raw_label).title(), "other"


def _normalize_value(value: str, category: str) -> str:
    cleaned = " ".join(str(value or "").split())
    if category in {"identifier", "contact"} and "@" not in cleaned:
        return re.sub(r"\s+", "", cleaned).upper()
    return cleaned


def _remember_candidate(seen: set[tuple[str, str, int]], candidate: FieldCandidate) -> bool:
    key = (
        candidate.label.strip().lower(),
        (candidate.normalized_value or candidate.raw_value or "").strip().lower(),
        candidate.page,
    )
    if key in seen:
        return False
    seen.add(key)
    return True


def _coerce_method(value: str) -> str:
    if value == "paddleocr":
        return "paddleocr"
    if value == "tesseract":
        return "tesseract"
    return "native"


def _normalize_label_key(value: str) -> str:
    cleaned = _clean_label(value).lower()
    return " ".join(cleaned.split())


def _clean_label(value: str) -> str:
    cleaned = re.sub(r"^[\s\-–•]+", "", str(value or ""))
    return cleaned.strip()


def _looks_like_identifier_value(value: str, line_text: str) -> bool:
    normalized = str(value or "").strip()
    compact = re.sub(r"[^A-Za-z0-9]", "", normalized)
    if len(re.sub(r"\D", "", normalized)) in {10, 12}:
        return True
    if not re.search(r"\d", compact):
        return False
    lowered_line = str(line_text or "").lower()
    return any(token in lowered_line for token in ("id", "number", "no", "registration", "roll", "pan", "aadhaar", "passport", "license", "mobile", "phone"))


def _looks_like_score_value(value: str, line_text: str) -> bool:
    normalized = str(value or "").strip()
    lowered_line = str(line_text or "").lower()
    if not any(token in lowered_line for token in ("cgpa", "gpa", "marks", "grade", "score", "percentage", "result")):
        return False
    if re.fullmatch(r"[A-F][+-]?", normalized, re.IGNORECASE):
        return any(token in lowered_line for token in ("grade", "result"))
    return bool(STRICT_SCORE_VALUE_PATTERN.fullmatch(normalized))


def _allow_candidate(candidate: FieldCandidate, *, document_type_hint: str) -> bool:
    label_key = _normalize_label_key(candidate.label)
    raw_value = " ".join(str(candidate.raw_value or "").split())
    lowered_value = raw_value.lower()
    lowered_source = str(candidate.source_text or "").lower()

    if not raw_value:
        return False
    if HEADER_ONLY_PATTERN.fullmatch(raw_value) and len(raw_value.split()) <= 3:
        return False
    if lowered_value in RESUME_SECTION_HEADERS:
        return False

    if candidate.category == "identifier":
        compact = re.sub(r"[^A-Za-z0-9]", "", raw_value)
        if not re.search(r"\d", compact):
            return False
    if candidate.category == "score" and not _looks_like_score_value(raw_value, lowered_source or candidate.label):
        return False
    if candidate.category in {"personal_name", "institution", "address"} and lowered_value in TECH_KEYWORDS:
        return False

    if document_type_hint == "resume":
        if candidate.category == "institution" and not any(token in label_key for token in ("institution", "university", "college", "school", "company", "organization", "board")):
            return False
        if candidate.category == "personal_name" and "name" not in label_key and candidate.page != 1:
            return False
        if label_key in SKILL_LABELS and candidate.category != "other":
            return False
    return True


def _retarget_resume_categories(candidate: FieldCandidate, *, document_type_hint: str) -> FieldCandidate:
    if document_type_hint != "resume":
        return candidate
    label_key = _normalize_label_key(candidate.label)
    if label_key in SKILL_LABELS and candidate.category != "other":
        return candidate.model_copy(
            update={
                "category": "other",
                "requires_verification": False,
            }
        )
    return candidate
