from __future__ import annotations


def build_input_normalization_node():
    def node(state):
        warnings = list(state.get("warnings") or [])
        nodes = list(state.get("nodes_executed") or [])
        nodes.append("input_normalization")
        return {
            "warnings": warnings,
            "nodes_executed": nodes,
        }

    return node
