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
    input_node = "node_input_normalization"
    understanding_node = "node_document_understanding"
    grouping_node = "node_credential_grouping"
    routing_node = "node_route_recommendation"
    explanation_node = "node_explanation_synthesis"
    consolidation_node = "node_output_consolidation"

    graph = StateGraph(AgentGraphState)
    graph.add_node(input_node, build_input_normalization_node())
    graph.add_node(understanding_node, build_document_understanding_node(provider))
    graph.add_node(grouping_node, build_credential_grouping_node(provider))
    graph.add_node(routing_node, build_route_recommendation_node(provider))
    graph.add_node(explanation_node, build_explanation_synthesis_node(provider))
    graph.add_node(consolidation_node, build_output_consolidation_node())
    graph.add_edge(START, input_node)
    graph.add_edge(input_node, understanding_node)
    graph.add_edge(understanding_node, grouping_node)
    graph.add_edge(grouping_node, routing_node)
    graph.add_edge(routing_node, explanation_node)
    graph.add_edge(explanation_node, consolidation_node)
    graph.add_edge(consolidation_node, END)
    return graph.compile()
