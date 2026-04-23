from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..verification_domain.adapters import build_session_credentials, build_session_verification_plan
from ..verification_domain.contracts import (
    DocumentProfile,
    SessionCredentialCollection,
    SessionVerificationPlan,
)
from ..verifier_execution.contracts import (
    CredentialVerificationBundleCollection,
    VerificationTaskResultCollection,
)
from .adapters import (
    apply_agent_enrichment_to_credentials,
    apply_agent_enrichment_to_document_profile,
    apply_agent_enrichment_to_verification_plan,
    merge_agent_explanations_into_audits,
)
from .contracts import (
    AGENT_PHASE_PASS_A,
    AGENT_PHASE_PASS_B,
    AGENT_RUN_STATUS_FAILED,
    AGENT_RUN_STATUS_NOT_STARTED,
    AGENT_RUN_STATUS_READY,
    AGENT_RUN_STATUS_RUNNING,
    AgentDocumentUnderstanding,
    AgentExplanationArtifactCollection,
    AgentRunSummary,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
    SessionAgentRunStatus,
)
from .graph import build_agent_graph, build_gemini_normalization_graph
from .policies import load_agent_runtime_policy, minimize_extraction_payload
from .prompts import load_prompt_bundle
from .providers import AgentProviderUnavailable, DeterministicProvider, NvidiaProvider


LOGGER = logging.getLogger(__name__)
_UNSET = object()


def normalize_extraction_payload(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    """Return Gemini-normalized extraction data without persisting AI output."""
    try:
        graph = build_gemini_normalization_graph()
        result = graph.invoke({"raw_extraction": extraction_payload})
    except Exception as exc:
        LOGGER.warning("AGENT_NORMALIZATION_FALLBACK error=%s", exc)
        return extraction_payload

    normalized = result.get("normalized_extraction") if isinstance(result, dict) else None
    if not isinstance(normalized, dict):
        LOGGER.warning("AGENT_NORMALIZATION_FALLBACK error=missing_normalized_extraction")
        return extraction_payload
    if result.get("fallback_used"):
        LOGGER.warning(
            "AGENT_NORMALIZATION_FALLBACK validation_errors=%s",
            result.get("validation_errors") or [],
        )
    return normalized


def build_agent_pass_a_artifacts(
    session_id: str,
    *,
    extraction_payload,
    document_profile,
    credentials,
    verification_plan,
) -> dict[str, Any]:
    return _run_agent_graph(
        phase=AGENT_PHASE_PASS_A,
        session_id=session_id,
        extraction_payload=extraction_payload,
        document_profile=document_profile,
        credentials=credentials,
        verification_plan=verification_plan,
    )


def build_agent_pass_b_artifacts(
    session_id: str,
    *,
    extraction_payload,
    document_profile,
    credentials,
    verification_plan,
    verification_task_results,
    credential_bundles,
    credential_audits,
    existing_document_understanding=None,
    existing_credential_candidates=None,
    existing_route_recommendations=None,
    existing_explanations=None,
) -> dict[str, Any]:
    return _run_agent_graph(
        phase=AGENT_PHASE_PASS_B,
        session_id=session_id,
        extraction_payload=extraction_payload,
        document_profile=document_profile,
        credentials=credentials,
        verification_plan=verification_plan,
        verification_task_results=verification_task_results,
        credential_bundles=credential_bundles,
        credential_audits=credential_audits,
        existing_document_understanding=existing_document_understanding,
        existing_credential_candidates=existing_credential_candidates,
        existing_route_recommendations=existing_route_recommendations,
        existing_explanations=existing_explanations,
    )


def persist_agent_artifacts(
    session,
    *,
    document_understanding=_UNSET,
    credential_candidates=_UNSET,
    route_recommendations=_UNSET,
    explanations=_UNSET,
    run_summary=_UNSET,
    agent_run_status=_UNSET,
    agent_run_error=_UNSET,
) -> None:
    # DEPRECATED PERSISTENCE PATH:
    # Agent outputs are processing-only in the worker architecture. Keep this
    # legacy writer temporarily for old imports/tests; do not call from the
    # verification worker.
    if document_understanding is not _UNSET:
        session.agent_document_understanding_payload = _dump_model(document_understanding)
    if credential_candidates is not _UNSET:
        session.agent_credential_candidates_payload = _dump_model(credential_candidates)
    if route_recommendations is not _UNSET:
        session.agent_route_recommendations_payload = _dump_model(route_recommendations)
    if explanations is not _UNSET:
        session.agent_explanations_payload = _dump_model(explanations)
    if run_summary is not _UNSET:
        session.agent_run_summary_payload = _dump_model(run_summary)
    if agent_run_status is not _UNSET:
        session.agent_run_status = agent_run_status
    if agent_run_error is not _UNSET:
        session.agent_run_error = agent_run_error


def build_and_persist_agent_pass_a(
    session,
    *,
    document_profile,
    credentials,
    verification_plan,
) -> dict[str, Any]:
    # DEPRECATED PERSISTENCE PATH:
    # Replaced in the worker pipeline by normalize_extraction_payload(), which
    # runs LangGraph/Gemini in memory and writes nothing to the session row.
    persist_agent_artifacts(
        session,
        agent_run_status=AGENT_RUN_STATUS_RUNNING,
        agent_run_error=None,
    )
    artifacts = build_agent_pass_a_artifacts(
        session.id,
        extraction_payload=session.extraction_payload,
        document_profile=document_profile,
        credentials=credentials,
        verification_plan=verification_plan,
    )
    persist_agent_artifacts(
        session,
        document_understanding=artifacts["document_understanding"],
        credential_candidates=artifacts["credential_candidates"],
        route_recommendations=artifacts["route_recommendations"],
        explanations=artifacts["explanations"],
        run_summary=artifacts["run_summary"],
        agent_run_status=artifacts["run_summary"].run_status,
        agent_run_error=None,
    )
    return artifacts


def build_and_persist_agent_pass_b(
    session,
    *,
    document_profile,
    credentials,
    verification_plan,
    verification_task_results,
    credential_bundles,
    credential_audits,
) -> dict[str, Any]:
    # DEPRECATED PERSISTENCE PATH:
    # Final agent artifacts are no longer part of core verification execution.
    persist_agent_artifacts(
        session,
        agent_run_status=AGENT_RUN_STATUS_RUNNING,
        agent_run_error=None,
    )
    artifacts = build_agent_pass_b_artifacts(
        session.id,
        extraction_payload=session.extraction_payload,
        document_profile=document_profile,
        credentials=credentials,
        verification_plan=verification_plan,
        verification_task_results=verification_task_results,
        credential_bundles=credential_bundles,
        credential_audits=credential_audits,
        existing_document_understanding=_load_model(
            AgentDocumentUnderstanding,
            session.agent_document_understanding_payload,
        ),
        existing_credential_candidates=_load_model(
            SessionAgentCredentialCandidateCollection,
            session.agent_credential_candidates_payload,
        ),
        existing_route_recommendations=_load_model(
            SessionAgentRouteRecommendationCollection,
            session.agent_route_recommendations_payload,
        ),
        existing_explanations=_load_model(
            AgentExplanationArtifactCollection,
            session.agent_explanations_payload,
        ),
    )
    persist_agent_artifacts(
        session,
        document_understanding=artifacts["document_understanding"],
        credential_candidates=artifacts["credential_candidates"],
        route_recommendations=artifacts["route_recommendations"],
        explanations=artifacts["explanations"],
        run_summary=artifacts["run_summary"],
        agent_run_status=artifacts["run_summary"].run_status,
        agent_run_error=None,
    )
    return artifacts


def mark_agent_failure(session, error: Exception | str) -> None:
    error_message = str(error)
    LOGGER.warning("AGENT_ORCHESTRATION_FAILED session_id=%s error=%s", session.id, error_message)
    persist_agent_artifacts(
        session,
        agent_run_status=AGENT_RUN_STATUS_FAILED,
        agent_run_error=error_message,
    )


def enrich_generalized_analysis(
    *,
    document_profile,
    credentials,
    verification_plan,
    agent_artifacts,
):
    policy = load_agent_runtime_policy()
    enriched_credentials = apply_agent_enrichment_to_credentials(
        credentials,
        agent_artifacts["credential_candidates"],
        classification_override_confidence=policy.classification_override_confidence,
    )
    enriched_plan = apply_agent_enrichment_to_verification_plan(
        verification_plan,
        enriched_credentials,
        agent_artifacts["credential_candidates"],
        agent_artifacts["route_recommendations"],
        route_override_confidence=policy.route_override_confidence,
    )
    enriched_profile = apply_agent_enrichment_to_document_profile(
        document_profile,
        agent_artifacts["document_understanding"],
        classification_override_confidence=policy.classification_override_confidence,
    )
    return {
        "document_profile": enriched_profile,
        "credentials": enriched_credentials,
        "verification_plan": enriched_plan,
    }


def enrich_credential_audits_with_agent_explanations(credential_audits, agent_artifacts):
    return merge_agent_explanations_into_audits(
        credential_audits,
        agent_artifacts["explanations"],
    )


def get_agent_document_understanding_for_session(session) -> AgentDocumentUnderstanding:
    persisted = _load_model(AgentDocumentUnderstanding, session.agent_document_understanding_payload)
    if persisted is not None:
        return persisted
    if not session.extraction_payload:
        return AgentDocumentUnderstanding(session_id=session.id)
    return build_agent_pass_a_artifacts(
        session.id,
        extraction_payload=session.extraction_payload,
        document_profile=_resolve_document_profile(session),
        credentials=_resolve_credentials(session),
        verification_plan=_resolve_verification_plan(session),
    )["document_understanding"]


def get_agent_credential_candidates_for_session(session) -> SessionAgentCredentialCandidateCollection:
    persisted = _load_model(SessionAgentCredentialCandidateCollection, session.agent_credential_candidates_payload)
    if persisted is not None:
        return persisted
    if not session.extraction_payload:
        return SessionAgentCredentialCandidateCollection(session_id=session.id)
    return build_agent_pass_a_artifacts(
        session.id,
        extraction_payload=session.extraction_payload,
        document_profile=_resolve_document_profile(session),
        credentials=_resolve_credentials(session),
        verification_plan=_resolve_verification_plan(session),
    )["credential_candidates"]


def get_agent_route_recommendations_for_session(session) -> SessionAgentRouteRecommendationCollection:
    persisted = _load_model(
        SessionAgentRouteRecommendationCollection,
        session.agent_route_recommendations_payload,
    )
    if persisted is not None:
        return persisted
    if not session.extraction_payload:
        return SessionAgentRouteRecommendationCollection(session_id=session.id)
    return build_agent_pass_a_artifacts(
        session.id,
        extraction_payload=session.extraction_payload,
        document_profile=_resolve_document_profile(session),
        credentials=_resolve_credentials(session),
        verification_plan=_resolve_verification_plan(session),
    )["route_recommendations"]


def get_agent_explanations_for_session(session) -> AgentExplanationArtifactCollection:
    persisted = _load_model(AgentExplanationArtifactCollection, session.agent_explanations_payload)
    if persisted is not None:
        return persisted
    return AgentExplanationArtifactCollection(
        session_id=session.id,
        document_type=_resolve_document_profile(session).document_type,
    )


def get_agent_run_summary_for_session(session) -> AgentRunSummary:
    persisted = _load_model(AgentRunSummary, session.agent_run_summary_payload)
    if persisted is not None:
        return persisted
    enrichment_metadata = ((session.extraction_payload or {}).get("enrichment_metadata") or {})
    return AgentRunSummary(
        session_id=session.id,
        run_status=_infer_agent_run_status(session),
        provider_used="deterministic",
        reasoning_model_used="deterministic",
        pii_model_used=enrichment_metadata.get("pii_model_used"),
        pii_enrichment_used=bool(enrichment_metadata.get("pii_enrichment_used")),
        warnings=[],
        fallback_used=False,
    )


def get_agent_run_status_for_session(session) -> SessionAgentRunStatus:
    run_summary = get_agent_run_summary_for_session(session)
    return SessionAgentRunStatus(
        session_id=session.id,
        workflow_state=session.status,
        agent_run_status=_infer_agent_run_status(session),
        agent_run_error=session.agent_run_error,
        provider_used=run_summary.provider_used,
        reasoning_model_used=run_summary.reasoning_model_used,
        pii_model_used=run_summary.pii_model_used,
        pii_enrichment_used=run_summary.pii_enrichment_used,
        fallback_used=run_summary.fallback_used,
        warnings=list(run_summary.warnings or []),
        document_understanding_available=bool(session.agent_document_understanding_payload),
        credential_candidates_available=bool(session.agent_credential_candidates_payload),
        route_recommendations_available=bool(session.agent_route_recommendations_payload),
        explanations_available=bool(session.agent_explanations_payload),
        run_summary_available=bool(session.agent_run_summary_payload),
    )


def _run_agent_graph(
    *,
    phase: str,
    session_id: str,
    extraction_payload,
    document_profile,
    credentials,
    verification_plan,
    verification_task_results=None,
    credential_bundles=None,
    credential_audits=None,
    existing_document_understanding=None,
    existing_credential_candidates=None,
    existing_route_recommendations=None,
    existing_explanations=None,
) -> dict[str, Any]:
    policy = load_agent_runtime_policy()
    if not policy.orchestration_enabled:
        enrichment_metadata = (extraction_payload or {}).get("enrichment_metadata") or {}
        empty_summary = AgentRunSummary(
            session_id=session_id,
            run_status=AGENT_RUN_STATUS_NOT_STARTED,
            provider_used="deterministic",
            reasoning_model_used="deterministic",
            pii_model_used=enrichment_metadata.get("pii_model_used"),
            pii_enrichment_used=bool(enrichment_metadata.get("pii_enrichment_used")),
            warnings=["Agent orchestration is disabled by policy."],
            fallback_used=False,
        )
        return {
            "document_understanding": existing_document_understanding or AgentDocumentUnderstanding(session_id=session_id),
            "credential_candidates": existing_credential_candidates or SessionAgentCredentialCandidateCollection(session_id=session_id, document_type=document_profile.document_type),
            "route_recommendations": existing_route_recommendations or SessionAgentRouteRecommendationCollection(session_id=session_id, document_type=document_profile.document_type),
            "explanations": existing_explanations or AgentExplanationArtifactCollection(session_id=session_id, document_type=document_profile.document_type),
            "run_summary": empty_summary,
        }

    provider, warnings, fallback_used = _resolve_provider(policy)
    minimized_payload = minimize_extraction_payload(
        extraction_payload,
        max_fields=policy.max_fields_for_provider,
        max_value_chars=policy.max_value_chars,
    )
    enrichment_metadata = (extraction_payload or {}).get("enrichment_metadata") or {}
    started_at = datetime.utcnow()
    state = {
        "session_id": session_id,
        "phase": phase,
        "extraction_payload": extraction_payload,
        "minimized_extraction_payload": minimized_payload,
        "document_type": document_profile.document_type,
        "document_profile": document_profile,
        "credentials": credentials,
        "verification_plan": verification_plan,
        "verification_task_results": verification_task_results,
        "credential_bundles": credential_bundles,
        "credential_audits": credential_audits,
        "existing_document_understanding": existing_document_understanding,
        "existing_credential_candidates": existing_credential_candidates,
        "existing_route_recommendations": existing_route_recommendations,
        "existing_explanations": existing_explanations,
        "prompt_text": load_prompt_bundle(),
        "warnings": warnings,
        "nodes_executed": [],
        "provider_name": provider.provider_key,
        "reasoning_model_used": (
            policy.nvidia_reasoning_model if provider.provider_key == "nvidia" else "deterministic"
        ),
        "pii_model_used": enrichment_metadata.get("pii_model_used"),
        "pii_enrichment_used": bool(enrichment_metadata.get("pii_enrichment_used")),
        "fallback_used": fallback_used,
        "started_at": started_at,
    }
    graph = build_agent_graph(provider)
    try:
        result = graph.invoke(state)
    except AgentProviderUnavailable as exc:
        if provider.provider_key != "nvidia":
            raise
        warnings = list(warnings)
        warnings.append(str(exc))
        fallback_provider = DeterministicProvider(policy)
        fallback_state = {
            **state,
            "warnings": warnings,
            "nodes_executed": [],
            "provider_name": fallback_provider.provider_key,
            "reasoning_model_used": "deterministic",
            "fallback_used": True,
        }
        result = build_agent_graph(fallback_provider).invoke(fallback_state)
    run_summary = result["run_summary"]
    if run_summary.started_at is None:
        run_summary.started_at = started_at
    return {
        "document_understanding": result["document_understanding"],
        "credential_candidates": result["credential_candidates"],
        "route_recommendations": result["route_recommendations"],
        "explanations": result["explanations"],
        "run_summary": run_summary,
    }


def _resolve_provider(policy):
    warnings: list[str] = []
    fallback_used = False
    if policy.provider_key == "nvidia":
        provider = NvidiaProvider(policy)
        available, reason = provider.is_available()
        if available:
            return provider, warnings, fallback_used
        if reason:
            warnings.append(reason)
        fallback_used = True
    return DeterministicProvider(policy), warnings, fallback_used


def _resolve_document_profile(session):
    persisted = _load_model(DocumentProfile, session.document_profile_payload)
    if persisted is not None:
        return persisted
    credentials = _resolve_credentials(session)
    return DocumentProfile(
        session_id=session.id,
        document_type=credentials.document_type,
        document_family="unknown",
        page_count=(session.extraction_payload or {}).get("page_count"),
    )


def _resolve_credentials(session):
    persisted = _load_model(SessionCredentialCollection, session.generalized_credentials_payload)
    if persisted is not None:
        return persisted
    return build_session_credentials(session.id, session.extraction_payload)


def _resolve_verification_plan(session):
    persisted = _load_model(SessionVerificationPlan, session.verification_plan_payload)
    if persisted is not None:
        return persisted
    credentials = _resolve_credentials(session)
    return build_session_verification_plan(
        session.id,
        session.extraction_payload,
        credentials=credentials,
    )


def _infer_agent_run_status(session) -> str:
    if session.agent_run_status and (
        str(session.agent_run_status) != AGENT_RUN_STATUS_NOT_STARTED
        or any(
            (
                session.agent_document_understanding_payload,
                session.agent_credential_candidates_payload,
                session.agent_route_recommendations_payload,
                session.agent_explanations_payload,
                session.agent_run_summary_payload,
            )
        )
    ):
        return str(session.agent_run_status)
    if session.agent_run_error:
        return AGENT_RUN_STATUS_FAILED
    if any(
        (
            session.agent_document_understanding_payload,
            session.agent_credential_candidates_payload,
            session.agent_route_recommendations_payload,
            session.agent_explanations_payload,
            session.agent_run_summary_payload,
        )
    ):
        return AGENT_RUN_STATUS_READY
    return AGENT_RUN_STATUS_NOT_STARTED


def _load_model(model_cls, payload: Any):
    if payload in (None, ""):
        return None
    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)
    except Exception:
        LOGGER.warning(
            "AGENT_ARTIFACT_LOAD_FAILED model=%s",
            getattr(model_cls, "__name__", str(model_cls)),
            exc_info=True,
        )
        return None


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value
