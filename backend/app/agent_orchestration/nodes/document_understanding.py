from __future__ import annotations


def build_document_understanding_node(provider):
    def node(state):
        nodes = list(state.get("nodes_executed") or [])
        nodes.append("document_understanding")
        if state.get("phase") != "PASS_A" and state.get("existing_document_understanding") is not None:
            return {
                "document_understanding": state["existing_document_understanding"],
                "nodes_executed": nodes,
            }

        understanding = provider.analyze_document(
            session_id=state["session_id"],
            extraction_payload=state.get("extraction_payload"),
            minimized_extraction_payload=state.get("minimized_extraction_payload"),
            document_profile=state["document_profile"],
            credentials=state["credentials"],
            prompt_text=state["prompt_text"]["document_understanding"],
        )
        return {
            "document_understanding": understanding,
            "nodes_executed": nodes,
        }

    return node
