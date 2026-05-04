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
    "raw_gemini_prompt",
    "raw_gemini_response",
    "raw_llm_output",
    "visual_info_raw",
    "layout_parsing_result_raw",
    "overall_ocr_res_raw",
    "rec_texts_raw",
    "full_page_text",
    "raw_verifier_request",
    "raw_verifier_response",
    "verifier_request_body",
    "verifier_response_body",
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

INTERNAL_ONLY_CODES = {"PP_CHATOCR_CHAT_STAGE_DISABLED", "PP_CHAT_OCR_CHAT_STAGE_DISABLED"}
CODE_LIST_KEYS = {"warnings", "reason_codes", "risk_flags", "ambiguity_flags", "active_exceptions"}

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
        sanitized_items = [_sanitize_value(item, key=key) for item in value]
        if key in CODE_LIST_KEYS:
            return [item for item in sanitized_items if str(item).upper() not in INTERNAL_ONLY_CODES]
        if key == "bounding_boxes":
            return _canonical_workspace_boxes(sanitized_items)
        return sanitized_items
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


def _canonical_workspace_boxes(value: list[Any], *, limit: int = 2) -> list[Any]:
    boxes: list[tuple[tuple[int, float, float, float, float], float, dict[str, Any]]] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            x0, y0, x1, y1 = bbox[:4]
        else:
            x0, y0, x1, y1 = item.get("x0"), item.get("y0"), item.get("x1"), item.get("y1")
        try:
            page = int(item.get("page_number") or item.get("page") or 1)
            coords = (float(x0), float(y0), float(x1), float(y1))
        except (TypeError, ValueError):
            continue
        normalized = (
            page,
            round(min(coords[0], coords[2]), 2),
            round(min(coords[1], coords[3]), 2),
            round(max(coords[0], coords[2]), 2),
            round(max(coords[1], coords[3]), 2),
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        area = max(0.0, normalized[3] - normalized[1]) * max(0.0, normalized[4] - normalized[2])
        payload = dict(item)
        payload["page"] = page
        payload["page_number"] = page
        payload["x0"], payload["y0"], payload["x1"], payload["y1"] = normalized[1], normalized[2], normalized[3], normalized[4]
        payload["bbox"] = [normalized[1], normalized[2], normalized[3], normalized[4]]
        boxes.append((normalized, area, payload))
    boxes.sort(key=lambda item: (item[1], item[0]))
    return [payload for _, _, payload in boxes[:limit]]
