from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from extraction.analysis.pipeline import build_evidence_lines, extract_field_candidates
from extraction.models import (
    CanonicalSchema,
    DocumentMetadata,
    ExtractedField,
    OCRMetadata,
    SafetyReport,
    SpatialTextToken,
)
from extraction.pipeline import extract_document_data_with_strategy as _phase3_extract_document_data_with_strategy
from extraction.security_gate import DocumentSafetyError, validate_document_intake


class LegacyExtractionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    is_successful: bool
    used_ocr: bool
    fields: CanonicalSchema = Field(default_factory=CanonicalSchema)
    raw_text: str = ""
    spatial_text_map: list[SpatialTextToken] = Field(default_factory=list)
    evidence_lines: list[Any] = Field(default_factory=list)
    field_candidates: list[Any] = Field(default_factory=list)
    metadata: DocumentMetadata | None = None
    ocr_metadata: OCRMetadata | None = None
    safety_report: SafetyReport | None = None
    reason_code: str | None = None
    error_message: str | None = None


def extract_document_data(file_path: str) -> LegacyExtractionResult:
    return extract_document_data_with_strategy(file_path, strategy="auto")


def extract_document_data_with_strategy(file_path: str, strategy: str = "auto") -> LegacyExtractionResult:
    path = Path(file_path)
    if path.suffix.lower() != ".pdf":
        return LegacyExtractionResult(
            is_successful=False,
            used_ocr=False,
            reason_code="UNSUPPORTED_FORMAT",
            raw_text="",
        )

    try:
        safety_report = validate_document_intake(str(path))
    except DocumentSafetyError as exc:
        return LegacyExtractionResult(
            is_successful=False,
            used_ocr=False,
            reason_code=exc.reason_code,
            error_message=exc.message,
            raw_text="",
            safety_report=exc.safety_report,
        )

    try:
        payload, extraction_method = _load_payload(path, strategy)
        return _build_legacy_result(path, payload, safety_report, extraction_method)
    except Exception as exc:
        return LegacyExtractionResult(
            is_successful=False,
            used_ocr=False,
            reason_code="UNEXPECTED_PIPELINE_ERROR",
            error_message=str(exc),
            raw_text="",
            safety_report=safety_report,
        )


def _load_payload(path: Path, strategy: str) -> tuple[dict[str, Any], str]:
    if strategy == "auto":
        native_result = _run_parse_worker(str(path), "native_text")
        if _should_fallback_to_hybrid(native_result):
            return _run_parse_worker(str(path), "hybrid"), "hybrid"
        return native_result, "native_text"
    return _run_parse_worker(str(path), strategy), strategy


def _should_fallback_to_hybrid(payload: dict[str, Any]) -> bool:
    raw_text = str(payload.get("raw_text") or "").strip()
    word_count = int(payload.get("word_count") or 0)
    density = float(payload.get("character_density") or 0.0)
    return not raw_text or word_count == 0 or density < 5.0


def _run_parse_worker(file_path: str, strategy: str) -> dict[str, Any]:
    phase3_strategy = "auto"
    if strategy == "native_text":
        phase3_strategy = "text_only"
    elif strategy in {"hybrid", "ocr"}:
        phase3_strategy = "auto"
    result = _phase3_extract_document_data_with_strategy(file_path, strategy=phase3_strategy)
    return result.model_dump(mode="json")


def _build_legacy_result(
    path: Path,
    payload: dict[str, Any],
    safety_report: SafetyReport,
    extraction_method: str,
) -> LegacyExtractionResult:
    spatial_text_map = [
        item if isinstance(item, SpatialTextToken) else SpatialTextToken.model_validate(item)
        for item in list(payload.get("spatial_text_map") or [])
    ]
    evidence_lines = build_evidence_lines(spatial_text_map)
    field_candidates = extract_field_candidates(
        raw_text=str(payload.get("raw_text") or ""),
        evidence_lines=evidence_lines,
        spatial_text_map=spatial_text_map,
        extraction_method="hybrid" if extraction_method == "hybrid" else "native_text",
        warnings=list(payload.get("warnings") or []),
    )
    fields = _build_canonical_schema(field_candidates)
    ocr_metadata = OCRMetadata.model_validate(
        _coerce_ocr_metadata(
            payload.get("ocr_metadata") or {},
            extraction_method=extraction_method,
            has_tokens=bool(spatial_text_map),
        )
    )
    metadata = DocumentMetadata(
        file_name=path.name,
        file_type=path.suffix.lower().lstrip("."),
        page_count=int(payload.get("page_count") or safety_report.page_count or 0),
        size_bytes=path.stat().st_size,
        text_char_count=len(str(payload.get("raw_text") or "")),
        extraction_method=extraction_method,
        character_density=float(payload.get("character_density") or safety_report.character_density or 0.0),
        min_resolution_dpi=float(safety_report.min_resolution_dpi or 0.0),
        is_scanned=bool(ocr_metadata.ocr_applied),
        sandboxed_processing=bool(safety_report.sandboxed),
    )
    return LegacyExtractionResult(
        is_successful=True,
        used_ocr=bool(ocr_metadata.ocr_applied),
        fields=fields,
        raw_text=str(payload.get("raw_text") or ""),
        spatial_text_map=spatial_text_map,
        evidence_lines=evidence_lines,
        field_candidates=field_candidates,
        metadata=metadata,
        ocr_metadata=ocr_metadata,
        safety_report=safety_report,
    )


def _build_canonical_schema(field_candidates: list[Any]) -> CanonicalSchema:
    schema = CanonicalSchema()
    for candidate in field_candidates:
        extracted = ExtractedField(
            value=candidate.raw_value,
            confidence=float(candidate.confidence),
            bounding_boxes=[candidate.bounding_box],
            match_type=candidate.provenance_method,
        )
        if candidate.label in {"full_name", "student_name"} and schema.candidate_name is None:
            schema.candidate_name = extracted
        elif candidate.label == "institution_name" and schema.institution is None:
            schema.institution = extracted
        elif candidate.label in {"board_name"} and schema.institution is None:
            schema.institution = extracted
        elif candidate.label in {"aadhaar_number", "pan_number", "roll_number", "registration_number", "document_number"} and schema.document_id is None:
            schema.document_id = extracted
        elif candidate.label in {"date", "date_of_birth", "issue_date"} and schema.issue_date is None:
            schema.issue_date = extracted
    return schema


def _default_ocr_metadata(extraction_method: str, has_tokens: bool) -> dict[str, Any]:
    engine_used = "paddleocr" if extraction_method == "hybrid" else "native_text"
    return {
        "method_used": engine_used,
        "fallback_triggered": extraction_method == "hybrid",
        "total_pages": 1,
        "ocr_pages": [1] if extraction_method == "hybrid" else [],
        "avg_confidence": 0.95 if extraction_method == "hybrid" else 1.0 if has_tokens else 0.0,
        "language_detected": "en",
        "engine_used": engine_used,
        "engines_used": [engine_used],
        "native_text_used": extraction_method != "hybrid",
        "ocr_applied": extraction_method == "hybrid",
        "fallback_used": extraction_method == "hybrid",
        "average_confidence": 0.95 if extraction_method == "hybrid" else 1.0 if has_tokens else None,
        "preprocessing_applied": [],
        "pages_ocrd": [1] if extraction_method == "hybrid" else [],
        "page_metadata": [],
        "warning_codes": [],
    }


def _coerce_ocr_metadata(payload: dict[str, Any], *, extraction_method: str, has_tokens: bool) -> dict[str, Any]:
    base = _default_ocr_metadata(extraction_method, has_tokens)
    merged = dict(base)
    merged.update(dict(payload or {}))
    return merged


__all__ = [
    "extract_document_data",
    "extract_document_data_with_strategy",
    "validate_document_intake",
    "_run_parse_worker",
]
