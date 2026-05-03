from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Sensitivity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class VerificationStatus(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class BoundingBox(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    width: float = Field(default=0.0)
    height: float = Field(default=0.0)
    page_number: Optional[int] = None
    bbox: Optional[list[float]] = None
    polygon: Optional[list[list[float]]] = None
    coordinate_space: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = None

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "width", round(float(self.x1) - float(self.x0), 2))
        object.__setattr__(self, "height", round(float(self.y1) - float(self.y0), 2))
        if self.page_number is None:
            object.__setattr__(self, "page_number", self.page)
        if self.bbox is None:
            object.__setattr__(self, "bbox", [self.x0, self.y0, self.x1, self.y1])


class SpatialTextToken(BaseModel):
    text: str
    bbox: list[float]
    page: int
    source: str = "native_text"
    confidence: float = 1.0
    polygon: Optional[list[list[float]]] = None


class EvidenceLine(BaseModel):
    page: int
    text: str
    bbox: BoundingBox
    token_indices: list[int] = Field(default_factory=list)
    source: str = "native_text"


class ExtractionSignals(BaseModel):
    regex_score: float = 0.0
    layout_score: float = 0.0
    llm_score: float = 0.0
    ner_score: float = 0.0
    ocr_confidence: float = 0.0
    semantic_score: float = 0.0
    frequency: int = 1


FieldCategory = Literal[
    "identifier",
    "personal_name",
    "date",
    "institution",
    "credential_title",
    "score",
    "address",
    "contact",
    "signature",
    "seal",
    "other",
]


ExtractionMethod = Literal["native", "paddleocr", "tesseract", "pp_chatocr_v4"]


DetectedBy = Literal["regex", "layout", "llm", "ner", "table"]


class FieldCandidate(BaseModel):
    field_id: str
    label: str
    raw_value: Optional[str] = None
    extracted_value: Optional[str] = None
    masked_value: Optional[str] = None
    normalized_value: Optional[str] = None
    category: FieldCategory
    page: int
    page_number: Optional[int] = None
    bbox: Optional[list[float]] = None
    polygon: Optional[list[list[float]]] = None
    coordinate_space: Optional[str] = None
    source: Optional[str] = None
    evidence_ref: Optional[str] = None
    evidence_line_id: Optional[str] = None
    ocr_performed: bool = False
    advanced_ocr_performed: bool = False
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: ExtractionSignals = Field(default_factory=ExtractionSignals)
    verification_status: VerificationStatus = VerificationStatus.GREEN
    is_pii: bool = False
    sensitivity: Sensitivity = Sensitivity.LOW
    requires_verification: bool = True
    source_text: Optional[str] = None
    extraction_method: ExtractionMethod = "native"
    detected_by: list[DetectedBy] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.page_number is None:
            object.__setattr__(self, "page_number", self.page)
        if self.raw_value is None and self.extracted_value is not None:
            object.__setattr__(self, "raw_value", self.extracted_value)
        if self.extracted_value is None and self.raw_value is not None:
            object.__setattr__(self, "extracted_value", self.raw_value)


CredentialDocumentType = Literal[
    "academic_degree",
    "academic_transcript",
    "certificate",
    "identity_document",
    "employment_letter",
    "financial_document",
    "license",
    "invoice",
    "generic",
]


class CredentialCandidate(BaseModel):
    credential_id: str
    document_type: CredentialDocumentType
    issuer: Optional[str] = None
    subject_name: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    field_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_notes: list[str] = Field(default_factory=list)
    validation_status: VerificationStatus = VerificationStatus.GREEN


class OCRPageMetadata(BaseModel):
    page: int
    engine: str
    used_native_text: bool = False
    average_confidence: Optional[float] = None
    preprocessing_applied: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)


class OCRMetadata(BaseModel):
    method_used: str
    fallback_triggered: bool
    total_pages: int
    ocr_pages: list[int] = Field(default_factory=list)
    avg_confidence: float = 0.0
    language_detected: Optional[str] = None
    engine_used: str = "native_text"
    engines_used: list[str] = Field(default_factory=list)
    native_text_used: bool = True
    ocr_applied: bool = False
    fallback_used: bool = False
    average_confidence: Optional[float] = None
    preprocessing_applied: list[str] = Field(default_factory=list)
    pages_ocrd: list[int] = Field(default_factory=list)
    page_metadata: list[OCRPageMetadata] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)


class ProcessingExtractionResult(BaseModel):
    session_id: str
    field_candidates: list[FieldCandidate] = Field(default_factory=list)
    credential_candidates: list[CredentialCandidate] = Field(default_factory=list)
    ocr_metadata: OCRMetadata
    raw_text_per_page: dict[int, str] = Field(default_factory=dict)
    page_count: int = 0
    document_type_hint: Optional[str] = None
    extraction_quality: float = 0.0


class FieldView(BaseModel):
    field_id: str
    label: str
    value_preview: str
    category: str
    page: int
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    confidence: float = 0.0
    is_pii: bool = False
    sensitivity: Sensitivity = Sensitivity.LOW
    verification_status: VerificationStatus = VerificationStatus.GREEN


class WorkspaceExtractionView(BaseModel):
    session_id: str
    field_views: list[FieldView] = Field(default_factory=list)
    credential_summaries: list[dict[str, Any]] = Field(default_factory=list)
    ocr_metadata: OCRMetadata
    page_count: int = 0
    document_type_hint: Optional[str] = None
    raw_text_persisted: bool = False
    pii_persisted: bool = False
    extraction_quality: float = 0.0


class ExtractionWarning(BaseModel):
    code: str
    message: str


class SafetyReport(BaseModel):
    sandboxed: bool = False
    malware_scan_engine: str = "unknown"
    malware_scan_passed: bool = False
    file_size_bytes: int = 0
    page_count: int = 0
    min_resolution_dpi: float = 0.0
    character_density: float = 0.0
    is_scanned: bool = False


class DocumentMetadata(BaseModel):
    file_name: str = ""
    file_type: str = ""
    page_count: int = 0
    size_bytes: int = 0
    text_char_count: int = 0
    extraction_method: str = "native"
    character_density: float = 0.0
    min_resolution_dpi: float = 0.0
    is_scanned: bool = False
    sandboxed_processing: bool = False


class ExtractedField(BaseModel):
    value: str
    confidence: float
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    match_type: str = "exact"


class CanonicalSchema(BaseModel):
    candidate_name: Optional[ExtractedField] = None
    institution: Optional[ExtractedField] = None
    credential_type: Optional[ExtractedField] = None
    issue_date: Optional[ExtractedField] = None
    document_id: Optional[ExtractedField] = None
    email: Optional[ExtractedField] = None
    phone_number: Optional[ExtractedField] = None


class GeneralizedAnalysisPayload(BaseModel):
    document_profile_payload: dict[str, Any] = Field(default_factory=dict)
    generalized_credentials_payload: list[dict[str, Any]] = Field(default_factory=list)
    verification_plan_payload: list[dict[str, Any]] = Field(default_factory=list)
    credential_audits_payload: list[dict[str, Any]] = Field(default_factory=list)
    verification_summary_payload: dict[str, Any] = Field(default_factory=dict)
    generalized_analysis_status: str = "completed"
    generalized_analysis_error: Optional[str] = None


class ExtractionResult(BaseModel):
    is_successful: bool
    used_ocr: bool
    fields: CanonicalSchema = Field(default_factory=CanonicalSchema)
    raw_text: str = ""
    raw_text_per_page: dict[int, str] = Field(default_factory=dict)
    spatial_text_map: list[SpatialTextToken] = Field(default_factory=list)
    evidence_lines: list[EvidenceLine] = Field(default_factory=list)
    field_candidates: list[FieldCandidate] = Field(default_factory=list)
    generalized_analysis: Optional[GeneralizedAnalysisPayload] = None
    metadata: Optional[DocumentMetadata] = None
    ocr_metadata: Optional[OCRMetadata] = None
    safety_report: Optional[SafetyReport] = None
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    reason_code: Optional[str] = None
    error_message: Optional[str] = None
    processing_result: Optional[ProcessingExtractionResult] = None
    workspace_view: Optional[WorkspaceExtractionView] = None
    extraction_method: Optional[str] = None
    ocr_performed: bool = False
    advanced_ocr_performed: bool = False
    layout_blocks: list[dict[str, Any]] = Field(default_factory=list)
    table_cells: list[dict[str, Any]] = Field(default_factory=list)
    page_count: int = 0
    field_count: int = 0
    engine_metadata: dict[str, Any] = Field(default_factory=dict)


class RoutedExtraction(BaseModel):
    page_texts: dict[int, str] = Field(default_factory=dict)
    spatial_tokens: list[SpatialTextToken] = Field(default_factory=list)
    tables_by_page: dict[int, list[list[list[str]]]] = Field(default_factory=dict)
    ocr_metadata: OCRMetadata
    page_confidence: dict[int, float] = Field(default_factory=dict)
    page_methods: dict[int, ExtractionMethod] = Field(default_factory=dict)
    page_count: int = 0
