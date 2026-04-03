from __future__ import annotations


def build_route_recommendation_node(provider):
    def node(state):
        nodes = list(state.get("nodes_executed") or [])
        nodes.append("route_recommendation")
        if state.get("phase") != "PASS_A" and state.get("existing_route_recommendations") is not None:
            return {
                "route_recommendations": state["existing_route_recommendations"],
                "nodes_executed": nodes,
            }

        recommendations = provider.recommend_routes(
            session_id=state["session_id"],
            document_understanding=state["document_understanding"],
            credential_candidates=state["credential_candidates"],
            verification_plan=state["verification_plan"],
            prompt_text=state["prompt_text"]["route_recommendation"],
        )
        return {
            "route_recommendations": recommendations,
            "nodes_executed": nodes,
        }

    return node
