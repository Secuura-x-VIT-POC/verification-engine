from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DbSession

from ..sessions.models import AuditEventRecord, AuditReceiptRecord, SealedNonceRecord
from ..sessions.models import Session as SessionModel
from .hmac_utils import generate_hmac_hex


AUDIT_UNSAFE_KEYS = {
    "raw_text",
    "raw_ocr",
    "raw_ocr_text",
    "raw_pdf",
    "raw_pdf_text",
    "gemini_response",
    "gemini_raw_response",
    "full_gemini_response",
    "prompt",
    "full_prompt",
    "response_body",
    "request_body",
    "reviewer_note",
    "raw_reviewer_note",
    "raw_value",
    "normalized_value",
    "verifier_raw_evidence",
    "raw_provider_body",
    "raw_response",
}


def store_audit_bundle(db: DbSession, receipt: dict, nonce: bytes) -> AuditReceiptRecord:
    receipt = assert_audit_safe_payload(receipt)
    receipt_record = AuditReceiptRecord(
        audit_event_id=str(receipt["audit_event_id"]),
        session_id=str(receipt["session_id"]),
        reviewer_ref=receipt["reviewer_ref"],
        document_commitment=receipt["document_commitment"],
        trust_outcome=receipt["trust_outcome"],
        reason_codes=receipt["reason_codes"],
        connector_ids=receipt.get("connector_ids", []),
        issued_at=receipt["issued_at"],
        key_version=receipt["key_version"],
        receipt_hash=receipt["receipt_hash"],
        reviewer_decision=receipt.get("reviewer_decision"),
        reviewer_note_hash=receipt.get("reviewer_note_hash"),
        finding_counts=receipt.get("finding_counts"),
        approved_at=receipt.get("approved_at"),
        rejected_at=receipt.get("rejected_at"),
        manual_review_at=receipt.get("manual_review_at"),
    )
    nonce_record = SealedNonceRecord(
        session_id=str(receipt["session_id"]),
        nonce_value=base64.b64encode(nonce).decode("ascii"),
    )
    audit_event = AuditEventRecord(
        session_id=str(receipt["session_id"]),
        event_type="AUDIT_RECEIPT_ISSUED",
        event_data=assert_audit_safe_payload({
            "audit_event_id": str(receipt["audit_event_id"]),
            "trust_outcome": receipt["trust_outcome"],
            "reason_codes": receipt["reason_codes"],
            "connector_ids": receipt.get("connector_ids", []),
        }),
    )

    db.add(receipt_record)
    db.add(nonce_record)
    db.add(audit_event)
    db.flush()
    return receipt_record


def upsert_final_review_receipt(
    db: DbSession,
    session: SessionModel,
    *,
    reviewer_ref: str,
    reviewer_decision: str,
    reviewer_note: str | None = None,
) -> AuditReceiptRecord:
    now = datetime.utcnow()
    note_hash = hash_reviewer_note(reviewer_note) if reviewer_note and reviewer_note.strip() else None
    finding_counts = assert_audit_safe_payload(_build_finding_counts(session))
    receipt = get_latest_audit_receipt(db, session.id)

    if receipt is None:
        receipt = AuditReceiptRecord(
            audit_event_id=str(uuid.uuid4()),
            session_id=session.id,
            reviewer_ref=reviewer_ref,
            document_commitment=_resolve_document_commitment(session),
            trust_outcome=session.trust_outcome or "UNKNOWN",
            reason_codes=list(session.reason_codes or []),
            connector_ids=list(session.connector_ids or []),
            issued_at=now,
            key_version="v1",
            receipt_hash="PENDING",
        )
        db.add(receipt)
    else:
        receipt.reviewer_ref = reviewer_ref
        receipt.trust_outcome = session.trust_outcome or receipt.trust_outcome or "UNKNOWN"
        receipt.reason_codes = list(session.reason_codes or [])
        receipt.connector_ids = list(session.connector_ids or [])

    receipt.reviewer_decision = reviewer_decision
    receipt.reviewer_note_hash = note_hash
    receipt.finding_counts = finding_counts
    receipt.approved_at = now if reviewer_decision == "APPROVED" else None
    receipt.rejected_at = now if reviewer_decision == "REJECTED" else None
    receipt.manual_review_at = now if reviewer_decision == "MANUAL_REVIEW_REQUIRED" else None
    receipt.receipt_hash = build_final_receipt_hash(receipt)

    audit_event = AuditEventRecord(
        session_id=session.id,
        event_type="FINAL_REVIEW_DECISION_RECORDED",
        event_data=assert_audit_safe_payload({
            "audit_event_id": receipt.audit_event_id,
            "reviewer_decision": reviewer_decision,
            "reviewer_note_hash_present": bool(note_hash),
            "finding_counts": finding_counts,
        }),
    )
    db.add(audit_event)
    session.audit_receipt_id = receipt.audit_event_id
    db.flush()
    return receipt


def hash_reviewer_note(reviewer_note: str) -> str:
    return generate_hmac_hex(reviewer_note.strip())


def serialize_audit_summary(receipt: AuditReceiptRecord, cleanup_status: str | None = None) -> dict[str, Any]:
    return assert_audit_safe_payload(
        {
            "audit_receipt_id": receipt.audit_event_id,
            "session_id": receipt.session_id,
            "document_commitment": receipt.document_commitment,
            "overall_outcome": receipt.trust_outcome,
            "reviewer_decision": receipt.reviewer_decision,
            "finding_counts": receipt.finding_counts or {},
            "reason_codes": list(receipt.reason_codes or []),
            "connector_ids": list(receipt.connector_ids or []),
            "issued_at": _serialize_dt(receipt.issued_at),
            "approved_at": _serialize_dt(receipt.approved_at),
            "rejected_at": _serialize_dt(receipt.rejected_at),
            "manual_review_at": _serialize_dt(receipt.manual_review_at),
            "reviewer_note_hash": receipt.reviewer_note_hash,
            "receipt_hash": receipt.receipt_hash,
            "signature": receipt.signature,
            "hash_chain_prev": receipt.hash_chain_prev,
            "cleanup_status": cleanup_status,
        }
    )


def assert_audit_safe_payload(payload: Any) -> Any:
    sanitized = _strip_audit_unsafe(payload)
    remaining_key = _find_unsafe_key(sanitized)
    if remaining_key:
        raise ValueError(f"Unsafe audit payload contains {remaining_key}")
    return sanitized


def build_final_receipt_hash(receipt: AuditReceiptRecord) -> str:
    payload = {
        "session_id": receipt.session_id,
        "document_commitment": receipt.document_commitment,
        "trust_outcome": receipt.trust_outcome,
        "reviewer_decision": receipt.reviewer_decision,
        "reviewer_note_hash": receipt.reviewer_note_hash,
        "finding_counts": receipt.finding_counts or {},
        "final_decision_at": _decision_timestamp(receipt),
    }
    return generate_hmac_hex(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def get_latest_audit_receipt(db: DbSession, session_id: str) -> AuditReceiptRecord | None:
    return (
        db.query(AuditReceiptRecord)
        .filter(AuditReceiptRecord.session_id == session_id)
        .order_by(AuditReceiptRecord.created_at.desc())
        .first()
    )


def _decision_timestamp(receipt: AuditReceiptRecord) -> str | None:
    value = receipt.approved_at or receipt.rejected_at or receipt.manual_review_at
    return value.isoformat() if value else None


def _resolve_document_commitment(session: SessionModel) -> str:
    return session.document_commitment or "UNAVAILABLE"


def _strip_audit_unsafe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_audit_unsafe(nested)
            for key, nested in value.items()
            if str(key).lower() not in AUDIT_UNSAFE_KEYS
        }
    if isinstance(value, list):
        return [_strip_audit_unsafe(item) for item in value]
    return value


def _find_unsafe_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).lower()
            if normalized_key in AUDIT_UNSAFE_KEYS:
                return normalized_key
            nested_match = _find_unsafe_key(nested)
            if nested_match:
                return nested_match
    elif isinstance(value, list):
        for item in value:
            nested_match = _find_unsafe_key(item)
            if nested_match:
                return nested_match
    return None


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _build_finding_counts(session: SessionModel) -> dict:
    summary = _summary_from_payload(getattr(session, "workspace_payload", None))
    counts = _counts_from_summary(summary)
    if counts is not None:
        return counts

    summary = {}
    if isinstance(session.verification_execution_summary_payload, dict):
        summary = session.verification_execution_summary_payload.get("summary") or {}
    counts = _counts_from_summary(summary)
    if counts is not None:
        return counts

    outcome = str(session.trust_outcome or "").upper()
    if outcome in {"GREEN", "AMBER", "RED"}:
        return {
            "green": 1 if outcome == "GREEN" else 0,
            "amber": 1 if outcome == "AMBER" else 0,
            "red": 1 if outcome == "RED" else 0,
        }

    return {
        "green": 0,
        "amber": 0,
        "red": 0,
        "unknown": True,
    }


def _summary_from_payload(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else {}


def _counts_from_summary(summary) -> dict | None:
    if not isinstance(summary, dict):
        return None
    counts = {
        "green": _coerce_count(summary.get("green_count")),
        "amber": _coerce_count(summary.get("amber_count")),
        "red": _coerce_count(summary.get("red_count")),
    }
    if any(count is not None for count in counts.values()):
        return {key: value or 0 for key, value in counts.items()}
    return None


def _coerce_count(value) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
