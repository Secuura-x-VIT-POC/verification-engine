from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from ..sessions.models import AuditEventRecord, AuditReceiptRecord, SealedNonceRecord
from ..sessions.models import Session as SessionModel
from .hmac_utils import generate_hmac_hex


def store_audit_bundle(db: DbSession, receipt: dict, nonce: bytes) -> AuditReceiptRecord:
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
        event_data={
            "audit_event_id": str(receipt["audit_event_id"]),
            "trust_outcome": receipt["trust_outcome"],
            "reason_codes": receipt["reason_codes"],
            "connector_ids": receipt.get("connector_ids", []),
        },
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
    finding_counts = _build_finding_counts(session)
    receipt = get_latest_audit_receipt(db, session.id)

    if receipt is None:
        receipt = AuditReceiptRecord(
            audit_event_id=str(uuid.uuid4()),
            session_id=session.id,
            reviewer_ref=reviewer_ref,
            document_commitment=session.document_commitment or "UNAVAILABLE",
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
        event_data={
            "audit_event_id": receipt.audit_event_id,
            "reviewer_decision": reviewer_decision,
            "reviewer_note_hash_present": bool(note_hash),
            "finding_counts": finding_counts,
        },
    )
    db.add(audit_event)
    session.audit_receipt_id = receipt.audit_event_id
    db.flush()
    return receipt


def hash_reviewer_note(reviewer_note: str) -> str:
    return generate_hmac_hex(reviewer_note.strip())


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


def _build_finding_counts(session: SessionModel) -> dict:
    summary = {}
    if isinstance(session.verification_execution_summary_payload, dict):
        summary = session.verification_execution_summary_payload.get("summary") or {}

    if isinstance(summary, dict):
        counts = {
            "green": _coerce_count(summary.get("green_count")),
            "amber": _coerce_count(summary.get("amber_count")),
            "red": _coerce_count(summary.get("red_count")),
        }
        if any(count is not None for count in counts.values()):
            return {key: value or 0 for key, value in counts.items()}

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


def _coerce_count(value) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
