from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class GeminiNormalizationState(TypedDict, total=False):
    raw_extraction: dict[str, Any]
    gemini_output: dict[str, Any]
    normalized_extraction: dict[str, Any]
    validation_errors: list[str]
    fallback_used: bool


class GeneralizedVerificationState(TypedDict, total=False):
    session_id: str
    filename: str | None
    file_path: str
    runtime_policy: Any
    extraction_payload: dict[str, Any]
    sanitized_extraction: dict[str, Any]
    raw_text: str
    policy: dict[str, Any]
    document_understanding: dict[str, Any]
    normalized_fields: list[dict[str, Any]]
    credential_groups: list[dict[str, Any]]
    verification_tasks: list[dict[str, Any]]
    verifier_results: list[dict[str, Any]]
    field_decisions: list[dict[str, Any]]
    final_verdict: dict[str, Any]
    workspace_payload: dict[str, Any]
    gemini_errors: list[str]
    gemini_fallback_used: bool
    audit_log: list[dict[str, Any]]
