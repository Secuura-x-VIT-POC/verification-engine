from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from extraction.models import (
    CanonicalSchema,
    DocumentMetadata,
    FieldCandidate,
    OCRMetadata,
    ProcessingExtractionResult,
    SafetyReport,
    SpatialTextToken,
    WorkspaceExtractionView,
)
from extraction.pipeline import extract_document_data_with_strategy as _phase3_extract_document_data_with_strategy
from extraction.security_gate import validate_document_intake


class LegacyExtractionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    is_successful: bool
    used_ocr: bool
    fields: CanonicalSchema = Field(default_factory=CanonicalSchema)
    raw_text: str = ""
    spatial_text_map: list[SpatialTextToken] = Field(default_factory=list)
    evidence_lines: list[Any] = Field(default_factory=list)
    field_candidates: list[FieldCandidate] = Field(default_factory=list)
    raw_text_per_page: dict[int, str] = Field(default_factory=dict)
    generalized_analysis: Any | None = None
    metadata: DocumentMetadata | None = None
    ocr_metadata: OCRMetadata | None = None
    safety_report: SafetyReport | None = None
    warnings: list[Any] = Field(default_factory=list)
    processing_result: ProcessingExtractionResult | None = None
    workspace_view: WorkspaceExtractionView | None = None
    layout_blocks: list[dict[str, Any]] = Field(default_factory=list)
    table_cells: list[dict[str, Any]] = Field(default_factory=list)
    extraction_method: str | None = None
    ocr_performed: bool = False
    advanced_ocr_performed: bool = False
    page_count: int = 0
    field_count: int = 0
    engine_metadata: dict[str, Any] = Field(default_factory=dict)
    reason_code: str | None = None
    error_message: str | None = None


def extract_document_data(file_path: str) -> LegacyExtractionResult:
    return extract_document_data_with_strategy(file_path, strategy="auto")


def extract_document_data_with_strategy(file_path: str, strategy: str = "auto") -> LegacyExtractionResult:
    try:
        result = _phase3_extract_document_data_with_strategy(file_path, strategy=strategy)
        payload = result.model_dump(mode="json")
        return LegacyExtractionResult.model_validate(payload)
    except Exception as exc:
        return LegacyExtractionResult(
            is_successful=False,
            used_ocr=False,
            reason_code="UNEXPECTED_PIPELINE_ERROR",
            error_message=str(exc),
            raw_text="",
        )


def _run_parse_worker(file_path: str, strategy: str) -> dict[str, Any]:
    result = _phase3_extract_document_data_with_strategy(file_path, strategy=strategy)
    return result.model_dump(mode="json")


__all__ = [
    "extract_document_data",
    "extract_document_data_with_strategy",
    "validate_document_intake",
    "_run_parse_worker",
]
