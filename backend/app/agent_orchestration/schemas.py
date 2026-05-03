from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


DecisionStatus = Literal["GREEN", "AMBER", "RED"]
VerifierExecutionStatus = Literal["VERIFIED", "MISMATCH", "TIMEOUT", "ERROR", "SKIPPED", "NOT_APPLICABLE"]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class BoundingBox(BaseModel):
    page: int = 1
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    page_number: int | None = None
    bbox: list[float] | None = None
    polygon: list[list[float]] | None = None
    coordinate_space: str | None = None
    source: str | None = None
    confidence: float | None = None


class GeminiDocumentUnderstanding(BaseModel):
    document_type: str = "unknown"
    document_type_confidence: float = 0.0
    likely_claim_types: list[str] = Field(default_factory=list)
    credential_group_hints: list[str] = Field(default_factory=list)
    mandatory_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    ambiguity_flags: list[str] = Field(default_factory=list)
    summary: str = ""
    explanation: str | None = ""
    unsafe_or_malformed: bool = False
    grounding_confidence: float = 0.0
    matching_score: float = 0.0
    visual_match_probability: float = 0.0
    risk_flags: list[str] = Field(default_factory=list)

    _confidence_fields = field_validator(
        "document_type_confidence",
        "grounding_confidence",
        "matching_score",
        "visual_match_probability",
        mode="before",
    )(lambda cls, value: _clamp(value or 0.0))


class GeminiNormalizedField(BaseModel):
    field_id: str
    label: str
    extracted_value: str = ""
    normalized_value: str = ""
    ai_confidence: float = 0.0
    grounding_confidence: float = 0.0
    mandatory: bool = False
    verifier_hint: str | None = None
    notes: list[str] = Field(default_factory=list)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)

    _confidence_fields = field_validator("ai_confidence", "grounding_confidence", mode="before")(
        lambda cls, value: _clamp(value or 0.0)
    )


class GeminiNormalizedFieldCollection(BaseModel):
    fields: list[GeminiNormalizedField] = Field(default_factory=list)


class SemanticNormalizedClaim(BaseModel):
    claim_id: str
    field_id: str | None = None
    raw_value: str | None = None
    label: str | None = None
    value_preview: str | None = None
    normalized_value: str = ""
    claim_type: str = "generic_claim"
    canonical_label: str | None = None
    document_context: str | None = None
    confidence: float = 0.0
    source: Literal["gemini", "deterministic_fallback"] | None = None
    normalization_source: Literal["gemini", "deterministic_fallback"] = "deterministic_fallback"
    requires_verification: bool = True
    reason: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    ambiguity_flags: list[str] = Field(default_factory=list)

    _confidence_fields = field_validator("confidence", mode="before")(
        lambda cls, value: _clamp(value or 0.0)
    )


class SemanticNormalizedClaimCollection(BaseModel):
    claims: list[SemanticNormalizedClaim] = Field(default_factory=list)


class GeminiCredentialGroup(BaseModel):
    group_id: str
    credential_id: str | None = None
    credential_type: str | None = None
    label: str
    claim_ids: list[str] = Field(default_factory=list)
    field_ids: list[str] = Field(default_factory=list)
    required_field_ids: list[str] = Field(default_factory=list)
    optional_field_ids: list[str] = Field(default_factory=list)
    connector_id: str | None = None
    claim_type: str = "document"
    assurance_required: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    group_confidence: float = 0.0
    optional: bool = False
    high_assurance: bool = False
    explanation: str = ""

    _confidence_fields = field_validator("group_confidence", mode="before")(
        lambda cls, value: _clamp(value or 0.0)
    )


class GeminiCredentialGroupCollection(BaseModel):
    groups: list[GeminiCredentialGroup] = Field(default_factory=list)


class RouteRecommendation(BaseModel):
    credential_id: str
    claim_type: str = "generic_claim"
    provider_candidates: list[dict[str, Any] | str] = Field(default_factory=list)
    preferred_provider_key: str | None = None
    provider_id: str | None = None
    assurance_required: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    priority: Literal["REQUIRED", "OPTIONAL"] = "REQUIRED"
    planner_reason: str = ""


class RouteRecommendationCollection(BaseModel):
    recommendations: list[RouteRecommendation] = Field(default_factory=list)


class VerificationTask(BaseModel):
    task_id: str
    credential_id: str | None = None
    field_id: str = ""
    label: str = ""
    connector_id: str = ""
    claim_type: str = "document"
    provider_candidates: list[dict[str, Any] | str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    assurance_required: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    priority: Literal["REQUIRED", "OPTIONAL"] = "REQUIRED"
    optional: bool = False
    high_assurance: bool = False
    input_payload: dict[str, Any] = Field(default_factory=dict)
    field_ids: list[str] = Field(default_factory=list)
    planner_reason: str = ""


class VerifierResult(BaseModel):
    task_id: str
    field_id: str
    connector_id: str
    status: VerifierExecutionStatus
    verification_confidence: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    source_api: str | None = None
    audit_message: str = ""
    optional: bool = False
    high_assurance: bool = False
    field_ids: list[str] = Field(default_factory=list)

    _confidence_fields = field_validator("verification_confidence", mode="before")(
        lambda cls, value: _clamp(value or 0.0)
    )


class FieldDecision(BaseModel):
    field_id: str
    label: str
    extracted_value: str = ""
    normalized_value: str = ""
    status: DecisionStatus
    ai_confidence: float = 0.0
    extraction_confidence: float = 0.0
    verification_confidence: float = 0.0
    grounding_confidence: float = 0.0
    final_confidence: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    source_api: str | None = None
    audit_message: str = ""
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    manual_review_required: bool = False
    verifier_refs: list[str] = Field(default_factory=list)

    _confidence_fields = field_validator(
        "ai_confidence",
        "extraction_confidence",
        "verification_confidence",
        "grounding_confidence",
        "final_confidence",
        mode="before",
    )(lambda cls, value: _clamp(value or 0.0))


class FinalVerdict(BaseModel):
    outcome: DecisionStatus
    reason_codes: list[str] = Field(default_factory=list)
    connector_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    risk_level: str = "LOW"
    matching_score: float = 0.0
    visual_match_probability: float = 0.0

    _confidence_fields = field_validator("matching_score", "visual_match_probability", mode="before")(
        lambda cls, value: _clamp(value or 0.0)
    )


class WorkspaceDocument(BaseModel):
    filename: str | None = None
    document_type: str = "unknown"
    page_count: int | None = None
    used_ocr: bool = False
    warnings: list[str] = Field(default_factory=list)
    highlights_count: int = 0


class WorkspaceSummary(BaseModel):
    total_fields: int = 0
    green_count: int = 0
    amber_count: int = 0
    red_count: int = 0
    matching_score: float = 0.0
    visual_match_probability: float = 0.0
    risk_level: str = "LOW"
    active_exceptions: list[str] = Field(default_factory=list)

    _confidence_fields = field_validator("matching_score", "visual_match_probability", mode="before")(
        lambda cls, value: _clamp(value or 0.0)
    )


class WorkspaceVerifierStatus(BaseModel):
    connector_id: str
    status: str
    reason_codes: list[str] = Field(default_factory=list)
    source_api: str | None = None
    confidence: float = 0.0
    optional: bool = False
    high_assurance: bool = False
    field_ids: list[str] = Field(default_factory=list)

    _confidence_fields = field_validator("confidence", mode="before")(lambda cls, value: _clamp(value or 0.0))


class WorkspaceAuditEntry(BaseModel):
    stage: str
    message: str
    level: str = "INFO"
    timestamp: str


class WorkspaceAction(BaseModel):
    action_id: str
    label: str
    enabled: bool = True


class WorkspacePayload(BaseModel):
    session_id: str
    status: str
    ui_status: str
    document: WorkspaceDocument
    summary: WorkspaceSummary
    fields: list[FieldDecision] = Field(default_factory=list)
    verifiers: list[WorkspaceVerifierStatus] = Field(default_factory=list)
    final_verdict: FinalVerdict
    audit: list[WorkspaceAuditEntry] = Field(default_factory=list)
    actions: list[WorkspaceAction] = Field(default_factory=list)
