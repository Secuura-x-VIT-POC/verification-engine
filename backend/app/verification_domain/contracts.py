from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


ANALYSIS_STATUS_NOT_STARTED = "NOT_STARTED"
ANALYSIS_STATUS_PROFILED = "PROFILED"
ANALYSIS_STATUS_CREDENTIALS_BUILT = "CREDENTIALS_BUILT"
ANALYSIS_STATUS_PLAN_BUILT = "PLAN_BUILT"
ANALYSIS_STATUS_AUDITS_ASSEMBLED = "AUDITS_ASSEMBLED"
ANALYSIS_STATUS_READY = "READY"
ANALYSIS_STATUS_FAILED = "FAILED"

AUDIT_STATUS_VERIFIED = "VERIFIED"
AUDIT_STATUS_MISMATCH = "MISMATCH"
AUDIT_STATUS_PARTIAL = "PARTIAL"
AUDIT_STATUS_UNVERIFIED = "UNVERIFIED"
AUDIT_STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"
AUDIT_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

OUTCOME_COLOR_GREEN = "green"
OUTCOME_COLOR_RED = "red"
OUTCOME_COLOR_AMBER = "amber"
OUTCOME_COLOR_NEUTRAL = "neutral"

FALLBACK_REASON_ENTRA_NOT_CONFIGURED = "ENTRA_NOT_CONFIGURED"
FALLBACK_REASON_LIVE_PROVIDER_DISABLED = "LIVE_PROVIDER_DISABLED"
FALLBACK_REASON_LOCAL_DEMO_VERIFICATION = "LOCAL_DEMO_VERIFICATION"
FALLBACK_REASON_SUPPLEMENTARY_PROVIDER_USED = "SUPPLEMENTARY_PROVIDER_USED"
FALLBACK_REASON_NO_EXECUTABLE_PROVIDER = "NO_EXECUTABLE_PROVIDER"
FALLBACK_REASON_MANUAL_REVIEW_ONLY = "MANUAL_REVIEW_ONLY"
FALLBACK_REASON_PROVIDER_ATTEMPT_FAILED = "PROVIDER_ATTEMPT_FAILED"


class ContractModel(BaseModel):
    class Config:
        extra = "forbid"


class BoundingBox(ContractModel):
    page: int | None = None
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None


class EvidenceItem(ContractModel):
    evidence_type: str
    source: str
    detail: dict[str, Any] = Field(default_factory=dict)


class DocumentProfile(ContractModel):
    session_id: str
    document_type: str = "unknown"
    document_family: str = "unknown"
    page_count: int | None = None
    extraction_methods_used: list[str] = Field(default_factory=list)
    pii_detected: bool = False
    detected_categories: list[str] = Field(default_factory=list)
    requires_manual_review: bool = False
    notes: list[str] = Field(default_factory=list)


class ExtractedCredential(ContractModel):
    credential_id: str
    label: str
    category: str
    value: Any | None = None
    normalized_value: str | None = None
    source_text: str | None = None
    confidence: float | None = None
    page: int | None = None
    bounding_box: BoundingBox | None = None
    is_pii: bool = False
    requires_verification: bool = False
    verification_recommended: bool = False
    verification_reason: str | None = None
    planning_status: str = "verification_eligible"
    eligibility_reason: str | None = None
    grouping_reason: str | None = None
    source_candidate_ids: list[str] = Field(default_factory=list)
    extraction_method: str = "unknown"


class VerificationTask(ContractModel):
    task_id: str
    credential_id: str
    claim_type: str  
    provider_candidates: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    assurance_required: str = "MEDIUM"  
    selected_provider: str | None = None
    status: str = "PENDING"
    reason_codes: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)


class VerifierRouteDecision(ContractModel):
    credential_id: str
    selected_verifier_key: str
    selected_verifier_label: str
    route_reason: str
    preferred_provider_key: str | None = None
    preferred_provider_label: str | None = None
    planned_provider_key: str | None = None
    planned_provider_label: str | None = None
    planned_execution_mode: str | None = None
    planned_is_live_result: bool = False
    planned_is_mock_result: bool = False
    planned_is_demo_result: bool = False
    fallback_reason: str | None = None
    fallback_verifiers: list[str] = Field(default_factory=list)
    manual_review_recommended: bool = False


class CredentialAudit(ContractModel):
    credential_id: str
    label: str
    document_value: Any | None = None
    normalized_value: str | None = None
    verifier_label: str
    audit_status: str = AUDIT_STATUS_UNVERIFIED
    outcome_color: str = OUTCOME_COLOR_AMBER
    explanation: str
    reason_codes: list[str] = Field(default_factory=list)
    matched_fields: dict[str, Any] = Field(default_factory=dict)
    mismatched_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    timestamp: datetime | None = None


class DocumentVerificationSummary(ContractModel):
    session_id: str
    document_type: str = "unknown"
    total_credentials_found: int = 0
    total_credentials_verified: int = 0
    green_count: int = 0
    amber_count: int = 0
    red_count: int = 0
    manual_review_count: int = 0
    overall_outcome: str | None = None
    overall_reason_codes: list[str] = Field(default_factory=list)


class SessionCredentialCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    credentials: list[ExtractedCredential] = Field(default_factory=list)
    context_fields: list[ExtractedCredential] = Field(default_factory=list)


class SessionVerificationPlan(ContractModel):
    session_id: str
    document_type: str = "unknown"
    route_decisions: list[VerifierRouteDecision] = Field(default_factory=list)
    tasks: list[VerificationTask] = Field(default_factory=list)


class CredentialAuditCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    audits: list[CredentialAudit] = Field(default_factory=list)


class SessionAnalysisStatus(ContractModel):
    session_id: str
    workflow_state: str
    generalized_analysis_status: str = ANALYSIS_STATUS_NOT_STARTED
    generalized_analysis_error: str | None = None
    document_profile_available: bool = False
    credentials_available: bool = False
    verification_plan_available: bool = False
    credential_audits_available: bool = False
    verification_summary_available: bool = False
