from __future__ import annotations

from datetime import datetime
from typing import Any

from ...inference import NvidiaChatClient, NvidiaInferenceError
from ..contracts import (
    AGENT_PHASE_PASS_A,
    AgentCredentialCandidate,
    AgentDocumentUnderstanding,
    AgentExplanationArtifact,
    AgentExplanationArtifactCollection,
    AgentRouteRecommendation,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
)
from .base import AgentProvider, AgentProviderUnavailable
from .deterministic import DeterministicProvider


class NvidiaProvider(AgentProvider):
    provider_key = "nvidia"
    external_provider = True

    def __init__(self, policy):
        super().__init__(policy)
        self.client = NvidiaChatClient()
        self.baseline_provider = DeterministicProvider(policy)

    def is_available(self) -> tuple[bool, str | None]:
        if not self.policy.external_provider_enabled:
            return False, "External agent providers are disabled by policy."
        if not self.policy.nvidia_reasoning_enabled:
            return False, "NVIDIA reasoning is disabled by configuration."
        available, reason = self.client.is_configured()
        if not available:
            return False, reason or "NVIDIA provider configuration is incomplete."
        return True, None

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
        baseline = self.baseline_provider.analyze_document(
            session_id=session_id,
            extraction_payload=extraction_payload,
            minimized_extraction_payload=minimized_extraction_payload,
            document_profile=document_profile,
            credentials=credentials,
            prompt_text=prompt_text,
        )
        payload = self._invoke_json(
            prompt_text=prompt_text,
            context={
                "task": "document_understanding",
                "session_id": session_id,
                "document_profile": _dump_model(document_profile),
                "credentials": _dump_model(credentials),
                "minimized_extraction_payload": minimized_extraction_payload,
                "baseline_output": _dump_model(baseline),
                "output_schema": {
                    "document_type_guess": "string",
                    "document_family_guess": "string",
                    "confidence": "number between 0 and 1",
                    "detected_sections": ["string"],
                    "detected_entities": [{"label": "string", "category": "string", "credential_id": "string|null"}],
                    "pii_signals": ["string"],
                    "credential_candidates": ["string"],
                    "reasoning_summary": "string",
                    "manual_review_recommended": "boolean",
                },
            },
        )
        understanding = AgentDocumentUnderstanding.model_validate(
            {
                "session_id": session_id,
                "document_type_guess": payload.get("document_type_guess", baseline.document_type_guess),
                "document_family_guess": payload.get("document_family_guess", baseline.document_family_guess),
                "confidence": payload.get("confidence", baseline.confidence),
                "detected_sections": payload.get("detected_sections", baseline.detected_sections),
                "detected_entities": payload.get("detected_entities", baseline.detected_entities),
                "pii_signals": payload.get("pii_signals", baseline.pii_signals),
                "credential_candidates": payload.get("credential_candidates", baseline.credential_candidates),
                "reasoning_summary": payload.get("reasoning_summary", baseline.reasoning_summary),
                "manual_review_recommended": bool(
                    payload.get("manual_review_recommended", False) or baseline.manual_review_recommended
                ),
            }
        )
        if not understanding.reasoning_summary:
            understanding.reasoning_summary = baseline.reasoning_summary
        return understanding

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
        baseline = self.baseline_provider.group_credentials(
            session_id=session_id,
            extraction_payload=extraction_payload,
            document_understanding=document_understanding,
            document_profile=document_profile,
            credentials=credentials,
            verification_plan=verification_plan,
            prompt_text=prompt_text,
        )
        payload = self._invoke_json(
            prompt_text=prompt_text,
            context={
                "task": "credential_grouping",
                "session_id": session_id,
                "document_profile": _dump_model(document_profile),
                "document_understanding": _dump_model(document_understanding),
                "credentials": _dump_model(credentials),
                "verification_plan": _dump_model(verification_plan),
                "baseline_output": _dump_model(baseline),
                "output_schema": {
                    "candidates": [
                        {
                            "candidate_id": "string",
                            "label": "string",
                            "category": "string",
                            "source_fields": ["string"],
                            "grouped_field_ids": ["string"],
                            "grouped_values": {"field": "value"},
                            "confidence": "number between 0 and 1",
                            "verification_recommended": "boolean",
                            "verification_reason": "string",
                            "possible_verifier_keys": ["string"],
                            "ambiguity_flags": ["string"],
                        }
                    ]
                },
            },
        )
        candidates = _validate_candidates(payload.get("candidates"), session_id, document_profile.document_type)
        merged_candidates = _merge_candidate_collections(baseline.candidates, candidates)
        document_understanding.credential_candidates = [candidate.candidate_id for candidate in merged_candidates]
        return SessionAgentCredentialCandidateCollection(
            session_id=session_id,
            document_type=document_profile.document_type,
            candidates=merged_candidates,
        )

    def recommend_routes(
        self,
        *,
        session_id: str,
        document_understanding: AgentDocumentUnderstanding,
        credential_candidates: SessionAgentCredentialCandidateCollection,
        verification_plan,
        prompt_text: str,
    ) -> SessionAgentRouteRecommendationCollection:
        baseline = self.baseline_provider.recommend_routes(
            session_id=session_id,
            document_understanding=document_understanding,
            credential_candidates=credential_candidates,
            verification_plan=verification_plan,
            prompt_text=prompt_text,
        )
        payload = self._invoke_json(
            prompt_text=prompt_text,
            context={
                "task": "route_recommendation",
                "session_id": session_id,
                "document_understanding": _dump_model(document_understanding),
                "credential_candidates": _dump_model(credential_candidates),
                "verification_plan": _dump_model(verification_plan),
                "baseline_output": _dump_model(baseline),
                "output_schema": {
                    "recommendations": [
                        {
                            "candidate_id": "string",
                            "recommended_verifier_key": "string",
                            "alternative_verifier_keys": ["string"],
                            "route_reason": "string",
                            "confidence": "number between 0 and 1",
                            "manual_review_recommended": "boolean",
                        }
                    ]
                },
            },
        )
        recommendations = _validate_recommendations(payload.get("recommendations"), session_id, verification_plan.document_type)
        merged = _merge_recommendation_collections(baseline.recommendations, recommendations)
        return SessionAgentRouteRecommendationCollection(
            session_id=session_id,
            document_type=verification_plan.document_type,
            recommendations=merged,
        )

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
        baseline = self.baseline_provider.generate_explanations(
            phase=phase,
            session_id=session_id,
            document_understanding=document_understanding,
            credential_candidates=credential_candidates,
            route_recommendations=route_recommendations,
            document_profile=document_profile,
            credentials=credentials,
            verification_plan=verification_plan,
            verification_task_results=verification_task_results,
            credential_bundles=credential_bundles,
            credential_audits=credential_audits,
            prompt_text=prompt_text,
        )
        payload = self._invoke_json(
            prompt_text=prompt_text,
            context={
                "task": "explanation_synthesis",
                "phase": phase,
                "session_id": session_id,
                "document_understanding": _dump_model(document_understanding),
                "credential_candidates": _dump_model(credential_candidates),
                "route_recommendations": _dump_model(route_recommendations),
                "document_profile": _dump_model(document_profile),
                "verification_plan": _dump_model(verification_plan),
                "verification_task_results": _dump_model(verification_task_results),
                "credential_bundles": _dump_model(credential_bundles),
                "credential_audits": _dump_model(credential_audits),
                "baseline_output": _dump_model(baseline),
                "output_schema": {
                    "explanations": [
                        {
                            "target_type": "document|candidate|credential",
                            "target_id": "string",
                            "explanation_kind": "string",
                            "summary": "string",
                            "structured_reasons": ["string"],
                            "caution_notes": ["string"],
                        }
                    ]
                },
            },
        )
        explanations = _validate_explanations(
            payload.get("explanations"),
            session_id=session_id,
            document_type=document_profile.document_type,
        )
        merged = _merge_explanation_collections(baseline.explanations, explanations)
        return AgentExplanationArtifactCollection(
            session_id=session_id,
            document_type=document_profile.document_type,
            explanations=merged,
        )

    def _invoke_json(self, *, prompt_text: str, context: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.chat_json(
                model=self.policy.nvidia_reasoning_model,
                system_prompt=(
                    f"{prompt_text.strip()}\n\n"
                    "Return valid JSON only. Preserve uncertainty. "
                    "Do not decide final verification truth or final document trust. "
                    "If uncertain, set manual_review_recommended to true or include caution notes."
                ),
                user_payload=context,
                timeout_ms=self.policy.timeout_ms,
                retry_budget=self.policy.nvidia_retry_budget,
            )
        except NvidiaInferenceError as exc:
            raise AgentProviderUnavailable(f"NVIDIA reasoning request failed: {exc}") from exc


def _validate_candidates(payload: Any, session_id: str, document_type: str) -> list[AgentCredentialCandidate]:
    candidates = payload if isinstance(payload, list) else []
    validated: list[AgentCredentialCandidate] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        validated.append(
            AgentCredentialCandidate.model_validate(
                {
                    "candidate_id": item.get("candidate_id"),
                    "label": item.get("label"),
                    "category": item.get("category", "unknown"),
                    "source_fields": item.get("source_fields") or [],
                    "grouped_field_ids": item.get("grouped_field_ids") or [],
                    "grouped_values": item.get("grouped_values") or {},
                    "confidence": item.get("confidence"),
                    "verification_recommended": item.get("verification_recommended", False),
                    "verification_reason": item.get("verification_reason"),
                    "possible_verifier_keys": item.get("possible_verifier_keys") or [],
                    "ambiguity_flags": item.get("ambiguity_flags") or [],
                }
            )
        )
    return validated


def _validate_recommendations(payload: Any, session_id: str, document_type: str) -> list[AgentRouteRecommendation]:
    recommendations = payload if isinstance(payload, list) else []
    validated: list[AgentRouteRecommendation] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        validated.append(
            AgentRouteRecommendation.model_validate(
                {
                    "candidate_id": item.get("candidate_id"),
                    "recommended_verifier_key": item.get("recommended_verifier_key", "manual_review"),
                    "alternative_verifier_keys": item.get("alternative_verifier_keys") or [],
                    "route_reason": item.get("route_reason") or "No model route reason was returned.",
                    "confidence": item.get("confidence"),
                    "manual_review_recommended": item.get("manual_review_recommended", False),
                }
            )
        )
    return validated


def _validate_explanations(payload: Any, *, session_id: str, document_type: str) -> list[AgentExplanationArtifact]:
    explanations = payload if isinstance(payload, list) else []
    validated: list[AgentExplanationArtifact] = []
    for item in explanations:
        if not isinstance(item, dict):
            continue
        validated.append(
            AgentExplanationArtifact.model_validate(
                {
                    "target_type": item.get("target_type", "document"),
                    "target_id": item.get("target_id", session_id),
                    "explanation_kind": item.get("explanation_kind", "support"),
                    "summary": item.get("summary") or "No model explanation was returned.",
                    "structured_reasons": item.get("structured_reasons") or [],
                    "caution_notes": item.get("caution_notes") or [],
                    "generated_at": datetime.utcnow(),
                }
            )
        )
    return validated


def _merge_candidate_collections(
    baseline: list[AgentCredentialCandidate],
    enriched: list[AgentCredentialCandidate],
) -> list[AgentCredentialCandidate]:
    merged: dict[str, AgentCredentialCandidate] = {}
    for candidate in baseline:
        merged[candidate.candidate_id] = candidate.model_copy(deep=True)
    for candidate in enriched:
        merged[candidate.candidate_id] = candidate
    return list(merged.values())


def _merge_recommendation_collections(
    baseline: list[AgentRouteRecommendation],
    enriched: list[AgentRouteRecommendation],
) -> list[AgentRouteRecommendation]:
    merged: dict[str, AgentRouteRecommendation] = {}
    for recommendation in baseline:
        merged[recommendation.candidate_id] = recommendation.model_copy(deep=True)
    for recommendation in enriched:
        merged[recommendation.candidate_id] = recommendation
    return list(merged.values())


def _merge_explanation_collections(
    baseline: list[AgentExplanationArtifact],
    enriched: list[AgentExplanationArtifact],
) -> list[AgentExplanationArtifact]:
    merged: dict[tuple[str, str, str], AgentExplanationArtifact] = {}
    for explanation in baseline:
        merged[(explanation.target_type, explanation.target_id, explanation.explanation_kind)] = explanation.model_copy(
            deep=True
        )
    for explanation in enriched:
        merged[(explanation.target_type, explanation.target_id, explanation.explanation_kind)] = explanation
    return list(merged.values())


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value
