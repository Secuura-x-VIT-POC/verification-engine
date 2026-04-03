from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ..verification_domain.contracts import ContractModel


AGENT_RUN_STATUS_NOT_STARTED = "NOT_STARTED"
AGENT_RUN_STATUS_RUNNING = "RUNNING"
AGENT_RUN_STATUS_READY = "READY"
AGENT_RUN_STATUS_FAILED = "FAILED"

AGENT_PHASE_PASS_A = "PASS_A"
AGENT_PHASE_PASS_B = "PASS_B"


class AgentDocumentUnderstanding(ContractModel):
    session_id: str
    document_type_guess: str = "unknown"
    document_family_guess: str = "unknown"
    confidence: float | None = None
    detected_sections: list[str] = Field(default_factory=list)
    detected_entities: list[dict[str, Any]] = Field(default_factory=list)
    pii_signals: list[str] = Field(default_factory=list)
    credential_candidates: list[str] = Field(default_factory=list)
    reasoning_summary: str = "No agent document understanding is available."
    manual_review_recommended: bool = False


class AgentCredentialCandidate(ContractModel):
    candidate_id: str
    label: str
    category: str
    source_fields: list[str] = Field(default_factory=list)
    grouped_field_ids: list[str] = Field(default_factory=list)
    grouped_values: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    verification_recommended: bool = False
    verification_reason: str | None = None
    possible_verifier_keys: list[str] = Field(default_factory=list)
    ambiguity_flags: list[str] = Field(default_factory=list)


class AgentRouteRecommendation(ContractModel):
    candidate_id: str
    recommended_verifier_key: str
    alternative_verifier_keys: list[str] = Field(default_factory=list)
    route_reason: str
    confidence: float | None = None
    manual_review_recommended: bool = False


class AgentExplanationArtifact(ContractModel):
    target_type: str
    target_id: str
    explanation_kind: str
    summary: str
    structured_reasons: list[str] = Field(default_factory=list)
    caution_notes: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class AgentRunSummary(ContractModel):
    session_id: str
    run_status: str = AGENT_RUN_STATUS_NOT_STARTED
    nodes_executed: list[str] = Field(default_factory=list)
    provider_used: str = "deterministic"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False


class SessionAgentCredentialCandidateCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    candidates: list[AgentCredentialCandidate] = Field(default_factory=list)


class SessionAgentRouteRecommendationCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    recommendations: list[AgentRouteRecommendation] = Field(default_factory=list)


class AgentExplanationArtifactCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    explanations: list[AgentExplanationArtifact] = Field(default_factory=list)


class SessionAgentRunStatus(ContractModel):
    session_id: str
    workflow_state: str
    agent_run_status: str = AGENT_RUN_STATUS_NOT_STARTED
    agent_run_error: str | None = None
    provider_used: str | None = None
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    document_understanding_available: bool = False
    credential_candidates_available: bool = False
    route_recommendations_available: bool = False
    explanations_available: bool = False
    run_summary_available: bool = False
