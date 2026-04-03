from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from .contracts import (
    AgentDocumentUnderstanding,
    AgentExplanationArtifactCollection,
    AgentRunSummary,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
)


class AgentGraphState(TypedDict, total=False):
    session_id: str
    phase: str
    extraction_payload: dict[str, Any] | None
    minimized_extraction_payload: dict[str, Any] | None
    document_type: str
    document_profile: Any
    credentials: Any
    verification_plan: Any
    verification_task_results: Any
    credential_bundles: Any
    credential_audits: Any
    existing_document_understanding: AgentDocumentUnderstanding | None
    existing_credential_candidates: SessionAgentCredentialCandidateCollection | None
    existing_route_recommendations: SessionAgentRouteRecommendationCollection | None
    existing_explanations: AgentExplanationArtifactCollection | None
    prompt_text: dict[str, str]
    warnings: list[str]
    nodes_executed: list[str]
    provider_name: str
    fallback_used: bool
    started_at: Any
    document_understanding: AgentDocumentUnderstanding
    credential_candidates: SessionAgentCredentialCandidateCollection
    route_recommendations: SessionAgentRouteRecommendationCollection
    explanations: AgentExplanationArtifactCollection
    run_summary: AgentRunSummary
