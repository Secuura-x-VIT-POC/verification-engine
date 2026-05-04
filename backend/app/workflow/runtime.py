from __future__ import annotations

import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError:  # pragma: no cover
        PdfReader = None  # type: ignore
from sqlalchemy.orm import Session as DbSession

from ..audit.service import get_latest_audit_receipt
from ..cleanup.controller import complete_cleanup, fail_cleanup, start_cleanup
from ..security.pdf_validator import read_pdf_security_sidecar
from ..sessions.constants import HUMAN_FINAL_STATES, SessionState, VERIFIED_STATES
from ..sessions.models import Session as SessionModel
from . import repository
from .failures import WorkflowProcessingError


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

LOGGER = logging.getLogger(__name__)
WARNING_VALUE_KEYS = ("code", "warning_code", "reason_code", "type", "stage", "error_code", "message")
INTERNAL_ONLY_WARNING_CODES = {"PP_CHATOCR_CHAT_STAGE_DISABLED", "PP_CHAT_OCR_CHAT_STAGE_DISABLED"}
UNSAFE_WARNING_MARKERS = (
    "RAW",
    "SECRET",
    "PRIVATE",
    "PROMPT",
    "FULL_RESPONSE",
    "RAW_RESPONSE",
    "GEMINI_RESPONSE",
    "MODEL_OUTPUT",
    "PROVIDER_RAW",
    "PROVIDER_BODY",
    "REQUEST_BODY",
    "RESPONSE_BODY",
    "REVIEWER_NOTE",
)


COMPATIBILITY_FIELD_ALIASES = {
    "name": {"name", "candidate_name", "holder", "subject", "full_name"},
    "issuer": {"issuer", "institution", "organization", "authority", "provider"},
    "credential": {"credential", "credential_type", "title", "certificate", "license", "claim"},
    "date": {"date", "issue_date", "issued_at", "expiry_date"},
    "id": {"id", "document_id", "identifier", "registration_number", "license_number"},
}

COMPATIBILITY_TRUST_FIELDS = [
    ("name", True),
    ("issuer", False),
    ("credential", False),
    ("date", False),
    ("id", False),
]

PROCESSING_STATES = {
    SessionState.VERIFYING,
}

CLEANUP_READY_STATES = HUMAN_FINAL_STATES | {
    SessionState.FAILED_RETRIABLE,
    SessionState.FAILED_PURGED,
    SessionState.ABANDONED_VERIFYING,
}

SENSITIVE_SESSION_CLEANUP_VALUES = {
    "file_path": None,
    "filename": None,
    "extraction_payload": None,
    "connector_payload": None,
    "document_profile_payload": None,
    "generalized_credentials_payload": None,
    "verification_plan_payload": None,
    "verification_task_results_payload": None,
    "credential_verification_bundles_payload": None,
    "verification_execution_summary_payload": None,
    "credential_audits_payload": None,
    "verification_summary_payload": None,
    "workspace_payload": None,
    "generalized_analysis_status": None,
    "generalized_analysis_error": None,
    "agent_document_understanding_payload": None,
    "agent_credential_candidates_payload": None,
    "agent_route_recommendations_payload": None,
    "agent_explanations_payload": None,
    "agent_run_summary_payload": None,
    "agent_run_status": None,
    "agent_run_error": None,
    "provider_execution_traces_payload": None,
    "provider_execution_status": None,
    "provider_execution_error": None,
    "provider_operating_mode": None,
    "demo_profile_key": None,
    "execution_environment_label": None,
    "provider_transition_notes": None,
    "verification_execution_status": None,
    "verification_execution_error": None,
}


def close_session(db: DbSession, session: SessionModel) -> SessionModel:
    start_cleanup(db, session.id)
    repository.transition_state(
        db,
        session.id,
        SessionState.PENDING_CLEANUP,
        extra_values={
            "purge_status": "IN_PROGRESS",
            "closed_at": datetime.utcnow(),
        },
    )
    db.commit()
    db.refresh(session)

    try:
        if session.file_path:
            file_path = Path(session.file_path)
            _delete_pdf_security_artifacts(file_path)
            if file_path.exists():
                file_path.unlink()

        repository.transition_state(
            db,
            session.id,
            SessionState.PURGE_COMPLETE,
            extra_values={
                **SENSITIVE_SESSION_CLEANUP_VALUES,
                "worker_phase": None,
                "lease_holder_id": None,
                "heartbeat_at": None,
                "purge_status": "COMPLETED",
                "purge_error": None,
            },
        )
        complete_cleanup(db, session.id)
        db.commit()
        db.refresh(session)
        return session
    except Exception as exc:
        repository.transition_state(
            db,
            session.id,
            SessionState.FAILED_PURGED,
            extra_values={
                "purge_status": "FAILED",
                "purge_error": str(exc),
            },
        )
        fail_cleanup(db, session.id, str(exc))
        db.commit()
        db.refresh(session)
        return session


def _delete_pdf_security_artifacts(file_path: Path) -> None:
    sidecar_path = Path(f"{file_path}.security.json")
    sidecar_payload = read_pdf_security_sidecar(file_path)
    quarantine_filename = str(sidecar_payload.get("quarantine_filename") or "").strip()
    if quarantine_filename and Path(quarantine_filename).name == quarantine_filename:
        quarantine_path = file_path.parent / "quarantine" / quarantine_filename
        if quarantine_path.exists():
            quarantine_path.unlink()
    if sidecar_path.exists():
        sidecar_path.unlink()


def serialize_session(db: DbSession, session: SessionModel) -> dict[str, Any]:
    audit_receipt = get_latest_audit_receipt(db, session.id)
    trust = None
    if session.trust_outcome:
        trust = {
            "outcome": session.trust_outcome,
            "reason_codes": session.reason_codes or [],
            "connector_ids": session.connector_ids or [],
        }

    audit = None
    if audit_receipt is not None:
        audit = {
            "audit_event_id": audit_receipt.audit_event_id,
            "logger_name": audit_receipt.reviewer_ref,
            "outcome": audit_receipt.trust_outcome,
            "reason_codes": audit_receipt.reason_codes or [],
            "issued_at": _serialize_dt(audit_receipt.issued_at),
            "document_commitment": audit_receipt.document_commitment,
            "connector_ids": audit_receipt.connector_ids or [],
            "key_version": audit_receipt.key_version,
            "receipt_hash": audit_receipt.receipt_hash,
            "signature": audit_receipt.signature,
            "hash_chain_prev": audit_receipt.hash_chain_prev,
            "reviewer_decision": audit_receipt.reviewer_decision,
            "reviewer_note_hash": audit_receipt.reviewer_note_hash,
            "finding_counts": audit_receipt.finding_counts,
            "approved_at": _serialize_dt(audit_receipt.approved_at),
            "rejected_at": _serialize_dt(audit_receipt.rejected_at),
            "manual_review_at": _serialize_dt(audit_receipt.manual_review_at),
        }

    return {
        "session_id": session.id,
        "status": session.status,
        "worker_phase": session.worker_phase,
        "filename": session.filename,
        "document_available": bool(session.file_path and Path(session.file_path).exists()),
        "trust_outcome": session.trust_outcome,
        "reason_codes": session.reason_codes or [],
        "connector_ids": session.connector_ids or [],
        "purge_status": session.purge_status,
        "purge_error": session.purge_error,
        "created_at": _serialize_dt(session.created_at),
        "uploaded_at": _serialize_dt(session.uploaded_at),
        "verified_at": _serialize_dt(session.verified_at),
        "closed_at": _serialize_dt(session.closed_at),
        "trust": trust,
        "audit": audit,
        "is_terminal": session.status in HUMAN_FINAL_STATES
        or session.status in {SessionState.PURGE_COMPLETE, SessionState.FAILED_RETRIABLE, SessionState.FAILED_PURGED},
    }


def is_ready_for_cleanup(session: SessionModel) -> bool:
    return session.status in CLEANUP_READY_STATES


def get_status_response(session: SessionModel) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "state": session.status,
        "processing": session.status in PROCESSING_STATES,
        "retriable": session.status == SessionState.FAILED_RETRIABLE,
    }


def get_result_response(session: SessionModel) -> dict[str, Any]:
    if session.trust_outcome and session.status in (
        VERIFIED_STATES
        | HUMAN_FINAL_STATES
        | {SessionState.PENDING_HUMAN_REVIEW}
    ):
        return {
            "session_id": session.id,
            "outcome": session.trust_outcome,
            "reason_codes": session.reason_codes or [],
            "connector_ids": session.connector_ids or [],
        }

    return {
        "session_id": session.id,
        "outcome": None,
        "reason_codes": session.reason_codes or [],
        "connector_ids": session.connector_ids or [],
        "state": session.status,
        "processing": session.status in PROCESSING_STATES,
        "retriable": session.status == SessionState.FAILED_RETRIABLE,
    }


def extract_document_payload(file_path: Path) -> dict[str, Any]:
    raw_result = _load_extraction_result(file_path)
    if raw_result.get("is_successful") is False:
        reason = raw_result.get("reason_code") or "extraction_failed"
        message = raw_result.get("error_message") or "PP-ChatOCRv4 extraction failed"
        raise WorkflowProcessingError(
            str(reason).lower(),
            message=f"PP-ChatOCRv4 extraction failed: {_safe_error(Exception(str(message)))}",
            context={"reason_code": reason},
        )
    page_count = _resolve_page_count(file_path, raw_result)
    document_type = _resolve_document_type(raw_result)
    generalized_entries = _collect_generalized_view_entries(raw_result)
    extracted_fields, confidence, bounding_boxes, field_details = _build_generalized_view_payload(generalized_entries)
    semantic_aliases = _build_semantic_aliases(raw_result)
    trust_fields = _build_trust_fields(semantic_aliases)

    return {
        "view": {
            "document_type": document_type,
            "page_count": page_count,
            "used_ocr": bool(raw_result.get("used_ocr")),
            "fields": extracted_fields,
            "confidence": confidence,
            "bounding_boxes": bounding_boxes,
            "field_details": field_details,
            "warnings": _safe_warning_codes(raw_result.get("warnings")),
            "reason_code": raw_result.get("reason_code"),
            "metadata": raw_result.get("metadata"),
            "ocr_metadata": raw_result.get("ocr_metadata"),
            "engine_metadata": raw_result.get("engine_metadata"),
            "enrichment_metadata": raw_result.get("enrichment_metadata"),
            "safety_report": raw_result.get("safety_report"),
            "spatial_text_map": raw_result.get("spatial_text_map") or [],
            "evidence_lines": raw_result.get("evidence_lines") or [],
            "field_candidates": raw_result.get("field_candidates") or [],
            "layout_blocks": raw_result.get("layout_blocks") or [],
            "table_cells": raw_result.get("table_cells") or [],
            "evidence_graph": raw_result.get("evidence_graph") or {},
            "generalized_analysis": raw_result.get("generalized_analysis"),
            "error_message": raw_result.get("error_message"),
        },
        "trust_input": {
            "is_unsafe": False,
            "critical_tamper_signal": False,
            "fields": trust_fields,
        },
        "connector_input": {
            "name": semantic_aliases.get("name", {}).get("value", ""),
            "degree": semantic_aliases.get("credential", {}).get("value", ""),
            "credential": semantic_aliases.get("credential", {}).get("value", ""),
            "institution": semantic_aliases.get("issuer", {}).get("value", ""),
            "issuer": semantic_aliases.get("issuer", {}).get("value", ""),
            "document_id": semantic_aliases.get("id", {}).get("value", ""),
        },
    }


def _collect_generalized_view_entries(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    generalized_analysis = raw_result.get("generalized_analysis") or {}
    generalized_credentials = generalized_analysis.get("generalized_credentials_payload")
    if isinstance(generalized_credentials, list) and generalized_credentials:
        return [entry for entry in generalized_credentials if isinstance(entry, dict)]

    field_candidates = raw_result.get("field_candidates")
    if isinstance(field_candidates, list) and field_candidates:
        return [entry for entry in field_candidates if isinstance(entry, dict)]

    return []


def _build_generalized_view_payload(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, float], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    extracted_fields: dict[str, str] = {}
    confidence: dict[str, float] = {}
    bounding_boxes: dict[str, dict[str, Any]] = {}
    field_details: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for index, entry in enumerate(entries, start=1):
        value = _normalize_string(
            entry.get("value")
            if "value" in entry
            else entry.get("extracted_value")
            or entry.get("masked_value")
            or entry.get("raw_value")
            or entry.get("normalized_value")
        )
        if not value:
            continue

        label = _normalize_string(entry.get("label")) or f"Credential {index}"
        key = _unique_view_key(
            _slug(label or _normalize_string(entry.get("category")) or _normalize_string(entry.get("credential_id")) or f"field-{index}"),
            seen_keys,
        )
        converted_boxes = _dedupe_converted_boxes(entry)
        page = converted_boxes[0]["page"] if converted_boxes else _coerce_int(entry.get("page"))
        page_number = _coerce_int(entry.get("page_number")) or page
        detail = {
            "key": key,
            "field_id": entry.get("field_id") or key,
            "label": label,
            "value": value,
            "extracted_value": value,
            "masked_value": entry.get("masked_value"),
            "normalized_value": _normalize_string(entry.get("normalized_value")) or value,
            "confidence": round(float(entry.get("confidence") or 0), 2) if value else 0,
            "is_mandatory": bool(entry.get("requires_verification")),
            "is_grounded": bool(converted_boxes),
            "bounding_boxes": converted_boxes,
            "bbox": converted_boxes[0].get("bbox") if converted_boxes else entry.get("bbox"),
            "polygon": entry.get("polygon") or (converted_boxes[0].get("polygon") if converted_boxes else None),
            "page_number": page_number,
            "coordinate_space": entry.get("coordinate_space") or (converted_boxes[0].get("coordinate_space") if converted_boxes else None),
            "evidence_ref": entry.get("evidence_ref") or entry.get("evidence_line_id"),
            "extraction_method": entry.get("extraction_method"),
            "category": entry.get("category"),
            "is_pii": bool(entry.get("is_pii")),
            "requires_verification": bool(entry.get("requires_verification", True)),
            "verification_reason": entry.get("verification_reason"),
        }
        if page is not None:
            detail["page"] = page

        extracted_fields[key] = value
        confidence[key] = detail["confidence"]
        if converted_boxes:
            bounding_boxes[key] = converted_boxes[0]
        field_details.append(detail)

    return extracted_fields, confidence, bounding_boxes, field_details


def _dedupe_converted_boxes(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw_boxes: list[Any] = []
    if isinstance(entry.get("bounding_boxes"), list):
        raw_boxes.extend(entry.get("bounding_boxes") or [])
    if isinstance(entry.get("bounding_box"), dict):
        raw_boxes.append(entry.get("bounding_box"))
    if isinstance(entry.get("bbox"), list):
        raw_boxes.append({"bbox": entry.get("bbox"), "page_number": entry.get("page_number") or entry.get("page")})

    converted: list[dict[str, Any]] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for raw in raw_boxes:
        if not isinstance(raw, dict):
            continue
        box = _convert_box(raw)
        key = (
            int(box.get("page_number") or box.get("page") or 1),
            round(float(box.get("x0") or 0), 2),
            round(float(box.get("y0") or 0), 2),
            round(float(box.get("x1") or 0), 2),
            round(float(box.get("y1") or 0), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        converted.append(box)
    return converted


def _build_semantic_aliases(raw_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    semantic_aliases: dict[str, dict[str, Any]] = {}
    fields = raw_result.get("fields") or {}
    for source_key, field in fields.items():
        if not isinstance(field, dict):
            continue
        api_key = _compatibility_api_key(source_key)
        if not api_key:
            continue
        _set_semantic_alias(semantic_aliases, api_key, field)

    for entry in _collect_generalized_view_entries(raw_result):
        api_key = _compatibility_api_key(
            entry.get("category")
            or entry.get("label")
            or entry.get("key")
            or entry.get("credential_id")
            or ""
        )
        if not api_key:
            continue
        _set_semantic_alias(
            semantic_aliases,
            api_key,
            {
                "value": entry.get("value") if "value" in entry else entry.get("extracted_value") or entry.get("normalized_value") or entry.get("raw_value") or entry.get("masked_value"),
                "confidence": entry.get("confidence"),
                "bounding_boxes": entry.get("bounding_boxes") or ([entry.get("bounding_box")] if isinstance(entry.get("bounding_box"), dict) else []),
            },
        )
    return semantic_aliases


def _build_trust_fields(semantic_aliases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    trust_fields: list[dict[str, Any]] = []
    for api_key, is_mandatory in COMPATIBILITY_TRUST_FIELDS:
        alias = semantic_aliases.get(api_key, {})
        value = alias.get("value") or ""
        trust_fields.append(
            {
                "name": api_key,
                "is_mandatory": is_mandatory,
                "is_grounded": bool(alias.get("is_grounded")) and bool(value),
                "value": value,
                "confidence": alias.get("confidence", 0),
            }
        )
    return trust_fields


def _compatibility_api_key(value: Any) -> str | None:
    normalized = _slug(_normalize_string(value)).replace("-", "_")
    for api_key, aliases in COMPATIBILITY_FIELD_ALIASES.items():
        if normalized == api_key or normalized in aliases:
            return api_key
    if any(token in normalized for token in ("issuer", "institution", "university", "authority", "organization")):
        return "issuer"
    if any(token in normalized for token in ("credential", "degree", "certificate", "license", "claim")):
        return "credential"
    if normalized.endswith("_id") or any(token in normalized for token in ("document_number", "identifier", "registration_number")):
        return "id"
    if "date" in normalized:
        return "date"
    if any(token in normalized for token in ("name", "holder", "subject")):
        return "name"
    return None


def _set_semantic_alias(
    semantic_aliases: dict[str, dict[str, Any]],
    api_key: str,
    field: dict[str, Any],
) -> None:
    value = _normalize_string(field.get("value"))
    if not value and semantic_aliases.get(api_key, {}).get("value"):
        return
    boxes = field.get("bounding_boxes") or []
    converted_boxes = [_convert_box(box) for box in boxes if isinstance(box, dict)]
    semantic_aliases[api_key] = {
        "value": value,
        "confidence": round(float(field.get("confidence") or 0), 2) if value else 0,
        "bounding_boxes": converted_boxes,
        "is_grounded": bool(converted_boxes),
    }


def _resolve_document_type(raw_result: dict[str, Any]) -> str:
    generalized_analysis = raw_result.get("generalized_analysis") or {}
    summary_payload = generalized_analysis.get("verification_summary_payload") or {}
    summary_document_type = str(summary_payload.get("document_type") or "").strip()
    if summary_document_type and summary_document_type not in {"generic_pdf_evidence", "structured_supporting_document"}:
        return _map_summary_document_type(summary_document_type)

    profile_payload = generalized_analysis.get("document_profile_payload") or {}
    family_hints = list(profile_payload.get("document_family_hints") or [])
    for hint in family_hints:
        mapped = _map_summary_document_type(str(hint))
        if mapped:
            return mapped

    return "generic_document"


def _map_summary_document_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"report_card", "transcript", "academic_record"}:
        return "report_card" if normalized == "report_card" else "academic_credential"
    if normalized in {"academic_credential", "academic_document"}:
        return "academic_credential"
    if normalized in {"identity_document", "license"}:
        return "identity_document"
    if normalized in {"certificate", "certificate_document"}:
        return "certificate_document"
    if normalized == "financial_document":
        return "financial_document"
    if normalized:
        return normalized
    return "generic_document"


def _normalize_string(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "field"


def _unique_view_key(base_key: str, seen_keys: set[str]) -> str:
    key = base_key
    suffix = 2
    while key in seen_keys:
        key = f"{base_key}-{suffix}"
        suffix += 1
    seen_keys.add(key)
    return key


def _first_box(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value:
        candidate = value[0]
        return candidate if isinstance(candidate, dict) else None
    if isinstance(value, dict):
        return value
    return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_connector_responses(extraction_payload: dict[str, Any], policy: dict | None = None) -> list[dict[str, Any]]:
    del extraction_payload, policy
    return []


def build_policy(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    del extraction_payload
    return {
        "required_fields": ["name", "institution", "credential", "id"],
        "min_confidence_threshold": 0.6,
        "require_connector": False,
        "requires_high_assurance": False,
        "required_connectors": [],
        "connector_policies": {},
    }


def _raise_on_processing_connector_failure(connector_responses: list[dict[str, Any]]) -> None:
    for response in connector_responses:
        status = str(response.get("status") or "").upper()
        assurance_class = str(response.get("assurance_class") or "OPTIONAL").upper()
        context = {
            "assurance_class": assurance_class,
            "connector_id": response.get("connector_id"),
        }

        if status == "TIMEOUT" and assurance_class == "HIGH":
            LOGGER.warning(
                "CONNECTOR_FAILURE connector_id=%s status=%s assurance_class=%s",
                response.get("connector_id"),
                status,
                assurance_class,
            )
            raise WorkflowProcessingError(
                "connector_timeout",
                message="Required connector timed out",
                context=context,
            )

        if status == "ERROR":
            LOGGER.warning(
                "CONNECTOR_FAILURE connector_id=%s status=%s assurance_class=%s",
                response.get("connector_id"),
                status,
                assurance_class,
            )
            raise WorkflowProcessingError(
                "transient_connector_error",
                message="Connector execution failed",
                context=context,
            )


def _load_extraction_result(file_path: Path) -> dict[str, Any]:
    try:
        from extraction.pipeline import extract_document_data
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise WorkflowProcessingError(
            "extraction_configuration_error",
            message=f"PP-ChatOCRv4 extraction pipeline unavailable: {_safe_error(exc)}",
        ) from exc

    try:
        result = extract_document_data(str(file_path))
    except Exception as exc:
        raise WorkflowProcessingError(
            "extraction_failed",
            message=f"PP-ChatOCRv4 extraction failed: {_safe_error(exc)}",
        ) from exc

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if hasattr(result, "dict"):
        return result.dict()
    return dict(result)


def _fallback_extract_document(file_path: Path) -> dict[str, Any]:
    raise WorkflowProcessingError(
        "extraction_configuration_error",
        message="PP-ChatOCRv4 extraction is required; no OCR fallback is configured.",
    )


def _convert_box(box: dict[str, Any]) -> dict[str, Any]:
    if isinstance(box.get("bbox"), list) and len(box["bbox"]) >= 4:
        x0, y0, x1, y1 = box["bbox"][:4]
    else:
        x0, y0, x1, y1 = box.get("x0", 0), box.get("y0", 0), box.get("x1", 0), box.get("y1", 0)
    page = int(box.get("page") or box.get("page_number") or 1)
    return {
        "page": page,
        "page_number": page,
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
        "bbox": [float(x0), float(y0), float(x1), float(y1)],
        "polygon": box.get("polygon"),
        "coordinate_space": box.get("coordinate_space"),
        "source": box.get("source"),
        "confidence": box.get("confidence"),
        "source_width": box.get("source_width"),
        "source_height": box.get("source_height"),
    }


def _safe_error(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:300]


def _safe_warning_codes(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _iter_warning_values(value):
        code = _safe_warning_code(item)
        if not code or code in INTERNAL_ONLY_WARNING_CODES or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def _iter_warning_values(value: Any):
    if value is None:
        return
    if hasattr(value, "model_dump"):
        try:
            yield from _iter_warning_values(value.model_dump(mode="json"))
            return
        except Exception:
            pass
    if isinstance(value, dict):
        for key in WARNING_VALUE_KEYS:
            if value.get(key) not in (None, ""):
                yield value.get(key)
                return
        yield "OCR_WARNING"
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_warning_values(item)
        return
    code_attr = getattr(value, "code", None)
    if code_attr not in (None, ""):
        yield code_attr
        return
    message_attr = getattr(value, "message", None)
    if message_attr not in (None, ""):
        yield message_attr
        return
    yield value


def _safe_warning_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if any(marker in upper for marker in UNSAFE_WARNING_MARKERS):
        return "WORKSPACE_WARNING_REDACTED"
    code = re.sub(r"[^A-Z0-9]+", "_", upper).strip("_")
    code = re.sub(r"_+", "_", code)
    if not code:
        return ""
    if len(code) > 96:
        return "WORKSPACE_WARNING_REDACTED"
    return code


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _resolve_page_count(file_path: Path, raw_result: dict[str, Any]) -> int | None:
    if raw_result.get("page_count") not in (None, ""):
        try:
            return int(raw_result["page_count"])
        except (TypeError, ValueError):
            pass

    try:
        if PdfReader is None:
            return None
        reader = PdfReader(str(file_path))
    except Exception:
        return None
    return len(reader.pages)
