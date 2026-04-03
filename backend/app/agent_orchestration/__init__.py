from __future__ import annotations

from importlib import import_module

from .contracts import (
    AGENT_PHASE_PASS_A,
    AGENT_PHASE_PASS_B,
    AGENT_RUN_STATUS_FAILED,
    AGENT_RUN_STATUS_NOT_STARTED,
    AGENT_RUN_STATUS_READY,
    AGENT_RUN_STATUS_RUNNING,
    AgentDocumentUnderstanding,
    AgentExplanationArtifact,
    AgentExplanationArtifactCollection,
    AgentRouteRecommendation,
    AgentRunSummary,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
    SessionAgentRunStatus,
)


_LAZY_IMPORTS = {
    "build_agent_graph": (".graph", "build_agent_graph"),
    "build_agent_pass_a_artifacts": (".service", "build_agent_pass_a_artifacts"),
    "build_agent_pass_b_artifacts": (".service", "build_agent_pass_b_artifacts"),
    "build_and_persist_agent_pass_a": (".service", "build_and_persist_agent_pass_a"),
    "build_and_persist_agent_pass_b": (".service", "build_and_persist_agent_pass_b"),
    "enrich_credential_audits_with_agent_explanations": (".service", "enrich_credential_audits_with_agent_explanations"),
    "enrich_generalized_analysis": (".service", "enrich_generalized_analysis"),
    "get_agent_credential_candidates_for_session": (".service", "get_agent_credential_candidates_for_session"),
    "get_agent_document_understanding_for_session": (".service", "get_agent_document_understanding_for_session"),
    "get_agent_explanations_for_session": (".service", "get_agent_explanations_for_session"),
    "get_agent_route_recommendations_for_session": (".service", "get_agent_route_recommendations_for_session"),
    "get_agent_run_status_for_session": (".service", "get_agent_run_status_for_session"),
    "get_agent_run_summary_for_session": (".service", "get_agent_run_summary_for_session"),
    "load_agent_runtime_policy": (".policies", "load_agent_runtime_policy"),
    "mark_agent_failure": (".service", "mark_agent_failure"),
    "persist_agent_artifacts": (".service", "persist_agent_artifacts"),
}


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute)
    globals()[name] = value
    return value


__all__ = [
    "AGENT_PHASE_PASS_A",
    "AGENT_PHASE_PASS_B",
    "AGENT_RUN_STATUS_FAILED",
    "AGENT_RUN_STATUS_NOT_STARTED",
    "AGENT_RUN_STATUS_READY",
    "AGENT_RUN_STATUS_RUNNING",
    "AgentDocumentUnderstanding",
    "AgentExplanationArtifact",
    "AgentExplanationArtifactCollection",
    "AgentRouteRecommendation",
    "AgentRunSummary",
    "SessionAgentCredentialCandidateCollection",
    "SessionAgentRouteRecommendationCollection",
    "SessionAgentRunStatus",
    "build_agent_graph",
    "build_agent_pass_a_artifacts",
    "build_agent_pass_b_artifacts",
    "build_and_persist_agent_pass_a",
    "build_and_persist_agent_pass_b",
    "enrich_credential_audits_with_agent_explanations",
    "enrich_generalized_analysis",
    "get_agent_credential_candidates_for_session",
    "get_agent_document_understanding_for_session",
    "get_agent_explanations_for_session",
    "get_agent_route_recommendations_for_session",
    "get_agent_run_status_for_session",
    "get_agent_run_summary_for_session",
    "load_agent_runtime_policy",
    "mark_agent_failure",
    "persist_agent_artifacts",
]
