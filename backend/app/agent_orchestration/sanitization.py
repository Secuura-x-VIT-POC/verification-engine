from __future__ import annotations

import re
from typing import Any, TypeVar

from .schemas import WorkspacePayload


UNSAFE_KEYS = {
    "raw_text",
    "raw_ocr_text",
    "raw_pdf_text",
    "pdf_text",
    "full_pdf_text",
    "full_ocr_text",
    "ocr_text",
    "source_text",
    "document_value",
    "raw_value",
    "spatial_text_map",
    "evidence_lines",
    "field_candidates",
    "generalized_analysis",
    "agent_private_notes",
    "agent_raw_output",
    "agent_document_understanding_payload",
    "agent_credential_candidates_payload",
    "agent_route_recommendations_payload",
    "agent_explanations_payload",
    "verifier_raw_evidence",
    "verifier_raw_response",
    "raw_verifier_response",
    "provider_raw_response",
    "raw_provider_body",
    "provider_raw_body",
    "raw_connector_response",
    "full_provider_response",
    "raw_result_summary",
    "raw_response",
    "raw_payload",
    "raw_candidates",
    "raw_pp_chatocr_output",
    "raw_llm_output",
    "visual_info_raw",
    "layout_parsing_result_raw",
    "overall_ocr_res_raw",
    "rec_texts_raw",
    "full_page_text",
    "raw_verifier_request",
    "raw_verifier_response",
    "input_payload",
    "evidence_payload",
    "request_body",
    "response_body",
    "full_gemini_prompt",
    "full_prompt",
    "gemini_prompt",
    "full_gemini_response",
    "full_response",
    "gemini_response",
    "gemini_raw_response",
    "reviewer_note",
    "private_reasoning",
    "raw_reviewer_note",
    "connector_payload",
    "provider_execution_traces_payload",
}

MASK_VALUE_KEYS = {
    "value",
    "extracted_value",
    "normalized_value",
    "document_value",
    "stored_value",
    "expected_value",
    "actual_value",
    "input_value",
    "credential_id",
    "document_id",
    "registration_number",
    "roll_number",
    "id_number",
    "passport_number",
    "license_number",
    "date_of_birth",
    "dob",
    "address",
    "email",
    "phone",
    "holder_name",
    "candidate_name",
}

EMAIL_RE = re.compile(r"^([^@\s])[^@\s]*(@[^@\s]+\.[^@\s]+)$")
DIGIT_RE = re.compile(r"\d")

T = TypeVar("T", WorkspacePayload, dict[str, Any])


def sanitize_workspace_payload(payload: T) -> T:
    """Return a frontend-safe workspace payload without mutating the input."""
    if isinstance(payload, WorkspacePayload):
        sanitized = _sanitize_value(payload.model_dump(mode="json"))
        return WorkspacePayload.model_validate(sanitized)  # type: ignore[return-value]
    if isinstance(payload, dict):
        return _sanitize_value(payload)  # type: ignore[return-value]
    return payload


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, nested in value.items():
            normalized_key = str(raw_key)
            if normalized_key in UNSAFE_KEYS:
                continue
            sanitized[normalized_key] = _sanitize_value(nested, key=normalized_key)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, key=key) for item in value]
    if key in MASK_VALUE_KEYS:
        return mask_sensitive_value(value)
    return value


def mask_sensitive_value(value: Any) -> Any:
    if value is None or value == "":
        return value
    text = str(value).strip()
    if not text:
        return text

    email_match = EMAIL_RE.match(text)
    if email_match:
        return f"{email_match.group(1)}***{email_match.group(2)}"

    compact_digits = re.sub(r"\D", "", text)
    if len(compact_digits) >= 4 and DIGIT_RE.search(text):
        return f"****{compact_digits[-4:]}"

    words = text.split()
    if len(words) >= 2 and all(_looks_like_name_word(word) for word in words[:3]):
        return " ".join(f"{word[0]}***" for word in words)

    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _looks_like_name_word(value: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z]", "", value)
    return bool(cleaned) and cleaned[0].isalpha()
