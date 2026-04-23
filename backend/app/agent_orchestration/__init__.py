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
    "build_gemini_normalization_graph": (".graph", "build_gemini_normalization_graph"),
    "load_agent_runtime_policy": (".policies", "load_agent_runtime_policy"),
    "normalize_extraction_payload": (".service", "normalize_extraction_payload"),
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
    "build_gemini_normalization_graph",
    "load_agent_runtime_policy",
    "normalize_extraction_payload",
]
