from __future__ import annotations

import operator
from typing import Any, Annotated
from typing_extensions import TypedDict

# We use operator.add for lists so LangGraph automatically appends new items.
# We use a custom reducer for booleans so if fallback is EVER triggered, it stays True.
def _reduce_bool(existing: bool, new: bool) -> bool:
    return existing or new

class GeneralizedVerificationState(TypedDict, total=False):
    session_id: str
    filename: str | None
    file_path: str
    
    # Context & Inputs
    runtime_policy: Any
    extraction_payload: dict[str, Any]
    sanitized_extraction: dict[str, Any]
    raw_text: str
    policy: dict[str, Any]
    
    # Structured Graph State (Passed between nodes)
    document_understanding: dict[str, Any]
    semantic_claims: list[dict[str, Any]]
    normalized_fields: list[dict[str, Any]]
    credential_groups: list[dict[str, Any]]
    verification_tasks: list[dict[str, Any]]
    domain_credentials: dict[str, Any]
    domain_verification_plan: dict[str, Any]
    verifier_results: list[dict[str, Any]]
    field_decisions: list[dict[str, Any]]
    final_verdict: dict[str, Any]
    workspace_payload: dict[str, Any]
    
    # Reducers: LangGraph will automatically append to these lists instead of overwriting.
    gemini_errors: Annotated[list[str], operator.add]
    audit_log: Annotated[list[dict[str, Any]], operator.add]
    gemini_fallback_used: Annotated[bool, _reduce_bool]
