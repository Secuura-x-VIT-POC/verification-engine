from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts import (
    AgentDocumentUnderstanding,
    AgentExplanationArtifactCollection,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
)
from ..policies import AgentRuntimePolicy


class AgentProviderUnavailable(RuntimeError):
    pass


class AgentProvider(ABC):
    provider_key = "base"
    external_provider = False

    def __init__(self, policy: AgentRuntimePolicy):
        self.policy = policy

    def is_available(self) -> tuple[bool, str | None]:
        return True, None

    @abstractmethod
    def analyze_document(
        self,
        *,
        session_id: str,
        extraction_payload,
        minimized_extraction_payload,
        document_profile,
        credentials,
        prompt_text: str,
    ) -> AgentDocumentUnderstanding:
        ...

    @abstractmethod
    def group_credentials(
        self,
        *,
        session_id: str,
        extraction_payload,
        document_understanding: AgentDocumentUnderstanding,
        document_profile,
        credentials,
        verification_plan,
        prompt_text: str,
    ) -> SessionAgentCredentialCandidateCollection:
        ...

    @abstractmethod
    def recommend_routes(
        self,
        *,
        session_id: str,
        document_understanding: AgentDocumentUnderstanding,
        credential_candidates: SessionAgentCredentialCandidateCollection,
        verification_plan,
        prompt_text: str,
    ) -> SessionAgentRouteRecommendationCollection:
        ...

    @abstractmethod
    def generate_explanations(
        self,
        *,
        phase: str,
        session_id: str,
        document_understanding: AgentDocumentUnderstanding,
        credential_candidates: SessionAgentCredentialCandidateCollection,
        route_recommendations: SessionAgentRouteRecommendationCollection,
        document_profile,
        credentials,
        verification_plan,
        verification_task_results,
        credential_bundles,
        credential_audits,
        prompt_text: str,
    ) -> AgentExplanationArtifactCollection:
        ...
