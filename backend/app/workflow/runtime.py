from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PyPDF2 import PdfReader
from sqlalchemy.orm import Session as DbSession

from ..audit.hmac_utils import generate_commitment, generate_nonce
from ..audit.receipt_generator import generate_receipt
from ..audit.service import get_latest_audit_receipt, store_audit_bundle
from ..cleanup.controller import complete_cleanup, fail_cleanup, start_cleanup
from ..connectors.broker import call_connector
from ..sessions.constants import SessionState, VERIFIED_STATES
from ..sessions.models import Session as SessionModel
from ..trust.trust_engine import evaluate_trust
from ..verifier_execution.service import (
    build_and_persist_execution_artifacts,
    mark_execution_failure,
)
from ..verification_domain.service import (
    build_and_persist_final_analysis,
    build_and_persist_initial_analysis,
    mark_analysis_failure,
)
from . import repository
from .failures import WorkflowProcessingError
from .service import call_connector_with_retry, handle_processing_failure


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))


FIELD_CONFIG = [
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

CLEANUP_READY_STATES = VERIFIED_STATES | {
    SessionState.FAILED_RETRIABLE,
    SessionState.FAILED_PURGED,
    SessionState.ABANDONED_VERIFYING,
}


def run_verification(db: DbSession, session: SessionModel, reviewer_ref: str) -> SessionModel:
    file_path = Path(session.file_path or "")

    now = datetime.utcnow()
    repository.transition_state(
        db,
        session.id,
        SessionState.VERIFYING,
        extra_values={
            "worker_phase": "EXTRACTING",
            "lease_id": reviewer_ref,
            "lease_holder_id": reviewer_ref,
            "lease_acquired_at": now,
            "heartbeat_at": now,
            "verify_started_at": session.verify_started_at or now,
            "version": SessionModel.version + 1,
        },
    )
    db.commit()
    db.refresh(session)

    try:
        if not session.file_path or not file_path.exists():
            raise WorkflowProcessingError(
                "document_missing",
                message=f"Document not found for session {session.id}",
            )

        extraction_payload = extract_document_payload(file_path)
        session.extraction_payload = extraction_payload["view"]
        _run_generalized_pass_a(session)
        session.worker_phase = "CONNECTOR_EVAL"
        session.heartbeat_at = datetime.utcnow()
        db.commit()

        policy = build_policy(extraction_payload)
        connector_responses = build_connector_responses(extraction_payload, policy)
        session.connector_payload = connector_responses
        session.heartbeat_at = datetime.utcnow()
        db.commit()
        db.refresh(session)
        _run_verification_execution(db, session)

        session.worker_phase = "TRUST_SCORING"
        session.heartbeat_at = datetime.utcnow()
        db.commit()
        _raise_on_processing_connector_failure(connector_responses)

        trust_result = evaluate_trust(extraction_payload["view"], connector_responses, policy)

        try:
            with file_path.open("rb") as source_file:
                document_bytes = source_file.read()

            nonce = generate_nonce()
            commitment = generate_commitment(document_bytes, nonce, "secuura-session")
            receipt = generate_receipt(session.id, reviewer_ref, commitment, trust_result)
            store_audit_bundle(db, receipt, nonce)
        except Exception as exc:
            raise WorkflowProcessingError(
                "audit_store_failure",
                message=str(exc),
            ) from exc

        repository.transition_state(
            db,
            session.id,
            STATUS_BY_OUTCOME[trust_result["outcome"]],
            extra_values={
                "worker_phase": "COMPLETED",
                "lease_id": None,
                "lease_holder_id": None,
                "lease_acquired_at": None,
                "heartbeat_at": None,
                "trust_outcome": trust_result["outcome"],
                "reason_codes": trust_result["reason_codes"],
                "connector_ids": trust_result["connector_ids"],
                "document_commitment": commitment,
                "audit_receipt_id": receipt["audit_event_id"],
                "verified_at": datetime.utcnow(),
            },
        )
        db.commit()
        db.refresh(session)
        _run_generalized_pass_b(db, session)
        return session
    except Exception as exc:
        failure_error = exc
        if not isinstance(exc, WorkflowProcessingError):
            failure_error = WorkflowProcessingError(
                "extraction_crash",
                message=str(exc),
            )

        failure_values = {}
        if session.extraction_payload is None:
            failure_values["extraction_payload"] = {
                "document_type": "academic_credential",
                "used_ocr": False,
                "fields": {},
                "confidence": {},
                "bounding_boxes": {},
                "field_details": [],
                "error_message": str(exc),
            }

        handle_processing_failure(
            db,
            session.id,
            failure_error,
            extra_values=failure_values,
        )
        db.refresh(session)
        _run_generalized_pass_b(db, session)
        return session


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
    extraction = session.extraction_payload or {}
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
        "generalized_analysis_status": session.generalized_analysis_status,
        "generalized_analysis_error": session.generalized_analysis_error,
        "agent_run_status": getattr(session, "agent_run_status", None),
        "agent_run_error": getattr(session, "agent_run_error", None),
        "provider_execution_status": getattr(session, "provider_execution_status", None),
        "provider_execution_error": getattr(session, "provider_execution_error", None),
        "provider_operating_mode": getattr(session, "provider_operating_mode", None),
        "demo_profile_key": getattr(session, "demo_profile_key", None),
        "execution_environment_label": getattr(session, "execution_environment_label", None),
        "provider_transition_notes": getattr(session, "provider_transition_notes", None),
        "verification_execution_status": session.verification_execution_status,
        "verification_execution_error": session.verification_execution_error,
        "purge_status": session.purge_status,
        "purge_error": session.purge_error,
        "created_at": _serialize_dt(session.created_at),
        "uploaded_at": _serialize_dt(session.uploaded_at),
        "verified_at": _serialize_dt(session.verified_at),
        "closed_at": _serialize_dt(session.closed_at),
        "extraction": extraction if extraction else None,
        "connectors": session.connector_payload or [],
        "trust": trust,
        "audit": audit,
        "is_terminal": session.status in VERIFIED_STATES
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
    fields = raw_result.get("fields") or {}

    extracted_fields: dict[str, str] = {}
    confidence: dict[str, float] = {}
    bounding_boxes: dict[str, dict[str, Any]] = {}
    field_details: list[dict[str, Any]] = []
    trust_fields: list[dict[str, Any]] = []

    for source_key, api_key, label, is_mandatory in FIELD_CONFIG:
        field = fields.get(source_key) or {}
        value = (field.get("value") or "").strip()
        boxes = field.get("bounding_boxes") or []
        converted_boxes = [_convert_box(box) for box in boxes]
        grounded = bool(converted_boxes)

        extracted_fields[api_key] = value
        confidence[api_key] = round(float(field.get("confidence") or 0), 2) if value else 0
        if converted_boxes:
            bounding_boxes[api_key] = converted_boxes[0]

        field_details.append(
            {
                "key": api_key,
                "label": label,
                "value": value,
                "confidence": confidence[api_key],
                "is_mandatory": is_mandatory,
                "is_grounded": grounded,
                "bounding_boxes": converted_boxes,
            }
        )
        trust_fields.append(
            {
                "name": api_key,
                "is_mandatory": is_mandatory,
                "is_grounded": grounded and bool(value),
                "value": value,
            }
        )

    return {
        "view": {
            "document_type": "academic_credential",
            "page_count": page_count,
            "used_ocr": bool(raw_result.get("used_ocr")),
            "fields": extracted_fields,
            "confidence": confidence,
            "bounding_boxes": bounding_boxes,
            "field_details": field_details,
            "error_message": raw_result.get("error_message"),
        },
        "trust_input": {
            "is_unsafe": False,
            "critical_tamper_signal": False,
            "fields": trust_fields,
        },
        "connector_input": {
            "name": extracted_fields.get("name", ""),
            "degree": _normalize_degree(extracted_fields.get("credential", "")),
            "institution": extracted_fields.get("institution", ""),
            "document_id": extracted_fields.get("id", ""),
        },
    }


def build_connector_responses(extraction_payload: dict[str, Any], policy: dict | None = None) -> list[dict[str, Any]]:
    connector_input = extraction_payload["connector_input"]
    institution = (connector_input.get("institution") or "").lower()
    name = connector_input.get("name")
    degree = connector_input.get("degree")
    if "vit" not in institution or not name or not degree:
        return []

    connector_policy = dict((policy or {}).get("connector_policies", {}).get("vit_registry", {}))
    connector_policy.setdefault("connector_id", "vit_registry")
    response = call_connector_with_retry(
        lambda payload: call_connector(payload, "vit_registry"),
        {
            "name": name,
            "degree": degree,
            "status": "verified",
        },
        connector_policy,
    )
    return [response]


def build_policy(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    institution = (extraction_payload["connector_input"].get("institution") or "").lower()
    should_query_registry = "vit" in institution
    return {
        "required_fields": ["name", "institution", "credential", "id"],
        "min_confidence_threshold": 0.6,
        "require_connector": should_query_registry,
        "requires_high_assurance": False,
        "required_connectors": ["vit_registry"] if should_query_registry else [],
        "connector_policies": {
            "vit_registry": {
                "connector_id": "vit_registry",
                "assurance_class": "HIGH" if should_query_registry else "OPTIONAL",
                "max_retries": 2,
                "deferred_retry_allowed": False,
            }
        },
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
            raise WorkflowProcessingError(
                "connector_timeout",
                message="Required connector timed out",
                context=context,
            )

        if status == "ERROR":
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
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    return dict(result)


def _fallback_extract_document(file_path: Path) -> dict[str, Any]:
    reader = PdfReader(str(file_path))
    raw_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    extracted = _apply_extraction_rules(raw_text)
    fields: dict[str, Any] = {}
    for key, value in extracted.items():
        if not value:
            fields[key] = None
            continue
        fields[key] = {
            "value": value,
            "confidence": 0.6,
            "bounding_boxes": [],
        }

    return {
        "is_successful": any(extracted.values()),
        "page_count": len(reader.pages),
        "used_ocr": False,
        "fields": fields,
        "raw_text": raw_text,
        "error_message": None,
    }


def _apply_extraction_rules(text: str) -> dict[str, str]:
    extracted = {
        "candidate_name": "",
        "institution": "",
        "credential_type": "",
        "issue_date": "",
        "document_id": "",
    }

    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if lines:
        extracted["candidate_name"] = lines[0]

    institution_match = re.search(
        (
            r"([A-Za-z.' ]*Vishwakarma Institute of Technology[A-Za-z, ]*|"
            r"[A-Za-z.' ]*Vellore Institute of Technology[A-Za-z, ]*|"
            r"\bVIT\b[A-Za-z, ]*)"
        ),
        text,
        re.IGNORECASE,
    )
    if institution_match:
        extracted["institution"] = institution_match.group(1).strip(", \n")

    credential_match = re.search(
        r"(Bachelor of Technology|B\.Tech|BTech|Bachelor of Engineering|B\.E\.|Master of Technology|M\.Tech)",
        text,
        re.IGNORECASE,
    )
    if credential_match:
        extracted["credential_type"] = credential_match.group(1).strip()

    date_match = re.search(
        r"([A-Z][a-z]{2,8}\s+\d{4}\s*-\s*(?:Present|\d{4}))",
        text,
        re.IGNORECASE,
    )
    if date_match:
        extracted["issue_date"] = date_match.group(1).strip()

    id_match = re.search(r"\b([A-Z0-9]{10,12})\b", text)
    if not id_match:
        id_match = re.search(r"\b(\d{10})\b", text)
    if id_match:
        extracted["document_id"] = id_match.group(1).strip()

    return extracted


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


def _run_generalized_pass_a(session: SessionModel) -> None:
    if session.extraction_payload is None:
        return

    try:
        build_and_persist_initial_analysis(session)
    except Exception as exc:  # pragma: no cover - defensive path
        mark_analysis_failure(session, exc)


def _run_generalized_pass_b(db: DbSession, session: SessionModel) -> None:
    if session.extraction_payload is None:
        return

    try:
        build_and_persist_final_analysis(session)
    except Exception as exc:  # pragma: no cover - defensive path
        mark_analysis_failure(session, exc)

    db.commit()
    db.refresh(session)


def _run_verification_execution(db: DbSession, session: SessionModel) -> None:
    if session.extraction_payload is None:
        return

    try:
        build_and_persist_execution_artifacts(session)
    except Exception as exc:  # pragma: no cover - defensive path
        mark_execution_failure(session, exc)

    db.commit()
    db.refresh(session)


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
