from __future__ import annotations


def build_credential_grouping_node(provider):
    def node(state):
        nodes = list(state.get("nodes_executed") or [])
        nodes.append("credential_grouping")
        if state.get("phase") != "PASS_A" and state.get("existing_credential_candidates") is not None:
            return {
                "credential_candidates": state["existing_credential_candidates"],
                "nodes_executed": nodes,
            }

        candidates = provider.group_credentials(
            session_id=state["session_id"],
            extraction_payload=state.get("extraction_payload"),
            document_understanding=state["document_understanding"],
            document_profile=state["document_profile"],
            credentials=state["credentials"],
            verification_plan=state["verification_plan"],
            prompt_text=state["prompt_text"]["credential_grouping"],
        )
        return {
            "credential_candidates": candidates,
            "nodes_executed": nodes,
        }

    return node
