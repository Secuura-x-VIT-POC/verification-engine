from __future__ import annotations

from datetime import datetime

from ..contracts import AGENT_RUN_STATUS_READY, AgentRunSummary


def build_output_consolidation_node():
    def node(state):
        nodes = list(state.get("nodes_executed") or [])
        nodes.append("output_consolidation")
        return {
            "nodes_executed": nodes,
            "run_summary": AgentRunSummary(
                session_id=state["session_id"],
                run_status=AGENT_RUN_STATUS_READY,
                nodes_executed=nodes,
                provider_used=state.get("provider_name", "deterministic"),
                started_at=state.get("started_at"),
                completed_at=datetime.utcnow(),
                warnings=list(state.get("warnings") or []),
                fallback_used=bool(state.get("fallback_used")),
            ),
        }

    return node
