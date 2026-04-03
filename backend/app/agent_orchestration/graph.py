from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    build_credential_grouping_node,
    build_document_understanding_node,
    build_explanation_synthesis_node,
    build_input_normalization_node,
    build_output_consolidation_node,
    build_route_recommendation_node,
)
from .state import AgentGraphState


def build_agent_graph(provider):
    graph = StateGraph(AgentGraphState)
    graph.add_node("input_normalization", build_input_normalization_node())
    graph.add_node("document_understanding", build_document_understanding_node(provider))
    graph.add_node("credential_grouping", build_credential_grouping_node(provider))
    graph.add_node("route_recommendation", build_route_recommendation_node(provider))
    graph.add_node("explanation_synthesis", build_explanation_synthesis_node(provider))
    graph.add_node("output_consolidation", build_output_consolidation_node())
    graph.add_edge(START, "input_normalization")
    graph.add_edge("input_normalization", "document_understanding")
    graph.add_edge("document_understanding", "credential_grouping")
    graph.add_edge("credential_grouping", "route_recommendation")
    graph.add_edge("route_recommendation", "explanation_synthesis")
    graph.add_edge("explanation_synthesis", "output_consolidation")
    graph.add_edge("output_consolidation", END)
    return graph.compile()
