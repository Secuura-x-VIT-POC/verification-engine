from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class SpatialTextToken(BaseModel):
    text: str
    bbox: List[float]
    page: int
    source: str = "native_text"
    confidence: float = 1.0


class EvidenceLine(BaseModel):
    page: int
    text: str
    bbox: BoundingBox
    token_indices: List[int] = Field(default_factory=list)
    source: str = "native_text"


class PageStructureProfile(BaseModel):
    page: int
    extraction_method: str
    word_count: int = 0
    character_density: float = 0.0
    section_headers: List[str] = Field(default_factory=list)
    likely_table: bool = False
    likely_form: bool = False


class ExtractedField(BaseModel):
    value: str
    confidence: float
    bounding_boxes: List[BoundingBox] = Field(default_factory=list)
    match_type: str = "none"


class ExtractionWarning(BaseModel):
    code: str
    message: str


class EnrichmentMetadata(BaseModel):
    pii_enrichment_used: bool = False
    pii_provider: Optional[str] = None
    pii_model_used: Optional[str] = None
    fallback_used: bool = False
    warning_codes: List[str] = Field(default_factory=list)


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
    extraction_method: str = "text"
    character_density: float = 0.0
    min_resolution_dpi: float = 0.0
    is_scanned: bool = False
    sandboxed_processing: bool = False


class CanonicalSchema(BaseModel):
    candidate_name: Optional[ExtractedField] = None
    institution: Optional[ExtractedField] = None
    credential_type: Optional[ExtractedField] = None
    issue_date: Optional[ExtractedField] = None
    document_id: Optional[ExtractedField] = None
    email: Optional[ExtractedField] = None
    phone_number: Optional[ExtractedField] = None


class FieldCandidate(BaseModel):
    candidate_id: str
    label: str
    category: str
    raw_value: str
    normalized_value: str
    source_text: str
    evidence_snippet: str
    page: int
    bounding_box: Optional[BoundingBox] = None
    confidence: float = 0.0
    grounding_match_type: str = "none"
    is_pii: bool = False
    requires_verification: bool = True
    verification_reason: str = ""
    extraction_method: str = "rule_based"
    source: str = "native_text"


class ExtractedCredential(BaseModel):
    credential_id: str
    label: str
    category: str
    value: str
    normalized_value: str
    source_text: str
    confidence: float
    page: int
    bounding_box: Optional[BoundingBox] = None
    is_pii: bool = False
    requires_verification: bool = True
    verification_reason: str = ""
    extraction_method: str = "rule_based"
    candidate_ids: List[str] = Field(default_factory=list)


class VerificationPlanItem(BaseModel):
    plan_item_id: str
    credential_id: str
    verifier_key: str
    verifier_type: str
    priority: str
    reason: str
    status: str = "planned"


class CredentialAudit(BaseModel):
    audit_id: str
    credential_id: str
    label: str
    status: str
    confidence: float
    evidence: str
    page: int
    bounding_box: Optional[BoundingBox] = None
    explanation: str
    source_provenance: str


class VerificationSummary(BaseModel):
    document_type: str
    total_candidates: int = 0
    total_credentials: int = 0
    total_pii_fields: int = 0
    total_verification_tasks: int = 0
    highlights_ready: bool = False
    summary_text: str = ""


class DocumentProfile(BaseModel):
    document_family_hints: List[str] = Field(default_factory=list)
    contains_pii: bool = False
    pii_categories: List[str] = Field(default_factory=list)
    likely_sections: List[str] = Field(default_factory=list)
    likely_tables_present: bool = False
    likely_form_present: bool = False
    issuer_hints: List[str] = Field(default_factory=list)
    structure_notes: List[str] = Field(default_factory=list)
    page_profiles: List[PageStructureProfile] = Field(default_factory=list)


class GeneralizedAnalysisPayload(BaseModel):
    document_profile_payload: DocumentProfile
    generalized_credentials_payload: List[ExtractedCredential] = Field(default_factory=list)
    verification_plan_payload: List[VerificationPlanItem] = Field(default_factory=list)
    credential_audits_payload: List[CredentialAudit] = Field(default_factory=list)
    verification_summary_payload: VerificationSummary
    generalized_analysis_status: str = "completed"
    generalized_analysis_error: Optional[str] = None


class ExtractionResult(BaseModel):
    is_successful: bool
    used_ocr: bool
    fields: CanonicalSchema
    raw_text: str
    spatial_text_map: List[SpatialTextToken] = Field(default_factory=list)
    evidence_lines: List[EvidenceLine] = Field(default_factory=list)
    field_candidates: List[FieldCandidate] = Field(default_factory=list)
    generalized_analysis: Optional[GeneralizedAnalysisPayload] = None
    metadata: Optional[DocumentMetadata] = None
    enrichment_metadata: Optional[EnrichmentMetadata] = None
    safety_report: Optional[SafetyReport] = None
    warnings: List[ExtractionWarning] = Field(default_factory=list)
    reason_code: Optional[str] = None
    error_message: Optional[str] = None
