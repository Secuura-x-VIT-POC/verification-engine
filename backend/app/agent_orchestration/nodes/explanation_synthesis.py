from __future__ import annotations


def build_explanation_synthesis_node(provider):
    def node(state):
        nodes = list(state.get("nodes_executed") or [])
        nodes.append("explanation_synthesis")
        if state.get("phase") == "PASS_A" and state.get("existing_explanations") is not None:
            return {
                "explanations": state["existing_explanations"],
                "nodes_executed": nodes,
            }

        explanations = provider.generate_explanations(
            phase=state["phase"],
            session_id=state["session_id"],
            document_understanding=state["document_understanding"],
            credential_candidates=state["credential_candidates"],
            route_recommendations=state["route_recommendations"],
            document_profile=state["document_profile"],
            credentials=state["credentials"],
            verification_plan=state["verification_plan"],
            verification_task_results=state.get("verification_task_results"),
            credential_bundles=state.get("credential_bundles"),
            credential_audits=state.get("credential_audits"),
            prompt_text=state["prompt_text"]["explanation_synthesis"],
        )
        return {
            "explanations": explanations,
            "nodes_executed": nodes,
        }

    return node
