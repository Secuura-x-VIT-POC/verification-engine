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
    from PyPDF2 import PdfReader  # type: ignore
from sqlalchemy.orm import Session as DbSession

from ..audit.service import get_latest_audit_receipt
from ..cleanup.controller import complete_cleanup, fail_cleanup, start_cleanup
from ..sessions.constants import HUMAN_FINAL_STATES, SessionState, VERIFIED_STATES
from ..sessions.models import Session as SessionModel
from . import repository
from .failures import WorkflowProcessingError


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

LOGGER = logging.getLogger(__name__)


TRUST_FIELD_CONFIG = [
    ("candidate_name", "name", "Candidate Name", True),
    ("institution", "institution", "Institution", True),
    ("credential_type", "credential", "Credential", True),
    ("issue_date", "date", "Issue Date", False),
    ("document_id", "id", "Document ID", True),
]

STATUS_BY_OUTCOME = {
    "GREEN": SessionState.VERIFIED_GREEN,
    "AMBER": SessionState.VERIFIED_AMBER,
    "RED": SessionState.VERIFIED_RED,
}

PROCESSING_STATES = {
    SessionState.VERIFYING,
}

CLEANUP_READY_STATES = HUMAN_FINAL_STATES | {
    SessionState.FAILED_RETRIABLE,
    SessionState.FAILED_PURGED,
    SessionState.ABANDONED_VERIFYING,
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
            if file_path.exists():
                file_path.unlink()

        repository.transition_state(
            db,
            session.id,
            SessionState.PURGE_COMPLETE,
            extra_values={
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
    if session.status in VERIFIED_STATES:
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
            "raw_text": raw_result.get("raw_text"),
            "warnings": raw_result.get("warnings") or [],
            "reason_code": raw_result.get("reason_code"),
            "metadata": raw_result.get("metadata"),
            "ocr_metadata": raw_result.get("ocr_metadata"),
            "enrichment_metadata": raw_result.get("enrichment_metadata"),
            "safety_report": raw_result.get("safety_report"),
            "spatial_text_map": raw_result.get("spatial_text_map") or [],
            "evidence_lines": raw_result.get("evidence_lines") or [],
            "field_candidates": raw_result.get("field_candidates") or [],
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
            "degree": _normalize_degree(semantic_aliases.get("credential", {}).get("value", "")),
            "institution": semantic_aliases.get("institution", {}).get("value", ""),
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
            else entry.get("raw_value") or entry.get("normalized_value")
        )
        source_text = _normalize_string(entry.get("source_text"))
        if not value and not source_text:
            continue

        label = _normalize_string(entry.get("label")) or f"Credential {index}"
        key = _unique_view_key(
            _slug(label or _normalize_string(entry.get("category")) or _normalize_string(entry.get("credential_id")) or f"field-{index}"),
            seen_keys,
        )
        box = _first_box(entry.get("bounding_boxes")) or entry.get("bounding_box")
        converted_boxes = [_convert_box(box)] if isinstance(box, dict) else []
        page = converted_boxes[0]["page"] if converted_boxes else _coerce_int(entry.get("page"))
        detail = {
            "key": key,
            "label": label,
            "value": value,
            "confidence": round(float(entry.get("confidence") or 0), 2) if value else 0,
            "is_mandatory": bool(entry.get("requires_verification")),
            "is_grounded": bool(converted_boxes),
            "bounding_boxes": converted_boxes,
            "source_text": source_text,
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


def _build_semantic_aliases(raw_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    semantic_aliases: dict[str, dict[str, Any]] = {}
    fields = raw_result.get("fields") or {}
    for source_key, api_key, _, _ in TRUST_FIELD_CONFIG:
        field = fields.get(source_key) or {}
        if not isinstance(field, dict):
            continue
        value = _normalize_string(field.get("value"))
        boxes = field.get("bounding_boxes") or []
        converted_boxes = [_convert_box(box) for box in boxes if isinstance(box, dict)]
        semantic_aliases[api_key] = {
            "value": value,
            "confidence": round(float(field.get("confidence") or 0), 2) if value else 0,
            "bounding_boxes": converted_boxes,
            "is_grounded": bool(converted_boxes),
        }
    return semantic_aliases


def _build_trust_fields(semantic_aliases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    trust_fields: list[dict[str, Any]] = []
    for _, api_key, _, is_mandatory in TRUST_FIELD_CONFIG:
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

    lowered_text = str(raw_result.get("raw_text") or "").lower()
    if any(token in lowered_text for token in ("report card", "marksheet", "mark sheet", "grade report")):
        return "report_card"
    if any(token in lowered_text for token in ("transcript", "semester", "cgpa", "student")):
        return "academic_credential"
    if any(token in lowered_text for token in ("aadhaar", "pan", "passport", "date of birth")):
        return "identity_document"
    if any(token in lowered_text for token in ("certificate", "course completion")):
        return "certificate_document"
    if any(token in lowered_text for token in ("invoice", "tax", "balance", "account")):
        return "financial_document"
    return "academic_credential"


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
    return "academic_credential"


def _normalize_string(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


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
        from extraction.parser.document_parser import extract_document_data
    except Exception as exc:  # pragma: no cover - fallback path is environment-dependent
        try:
            fallback = _fallback_extract_document(file_path)
        except Exception as fallback_exc:
            raise WorkflowProcessingError(
                "malformed_document",
                message=str(fallback_exc),
            ) from fallback_exc

        fallback["error_message"] = f"Extraction pipeline unavailable: {exc}"
        return fallback

    try:
        result = extract_document_data(str(file_path))
    except Exception as exc:
        try:
            fallback = _fallback_extract_document(file_path)
        except Exception as fallback_exc:
            raise WorkflowProcessingError(
                "malformed_document",
                message=str(fallback_exc),
            ) from fallback_exc

        fallback["error_message"] = str(exc)
        return fallback

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if hasattr(result, "dict"):
        return result.dict()
    return dict(result)


def _fallback_extract_document(file_path: Path) -> dict[str, Any]:
    reader = PdfReader(str(file_path))
    raw_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return {
        "is_successful": bool(raw_text.strip()),
        "page_count": len(reader.pages),
        "used_ocr": False,
        "fields": {},
        "raw_text": raw_text,
        "field_candidates": [],
        "generalized_analysis": None,
        "ocr_metadata": None,
        "enrichment_metadata": None,
        "error_message": None,
    }


def _normalize_degree(value: str) -> str:
    normalized = value.lower().replace(".", "").replace(" ", "")
    if normalized in {"btech", "bacheloroftechnology"}:
        return "BTech"
    if normalized in {"be", "bachelorofengineering"}:
        return "BE"
    if normalized in {"mtech", "masteroftechnology"}:
        return "MTech"
    return value.strip()


def _convert_box(box: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": int(box.get("page", 1)),
        "x0": float(box.get("x0", 0)),
        "y0": float(box.get("y0", 0)),
        "x1": float(box.get("x1", 0)),
        "y1": float(box.get("y1", 0)),
    }


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
        reader = PdfReader(str(file_path))
    except Exception:
        return None
    return len(reader.pages)
