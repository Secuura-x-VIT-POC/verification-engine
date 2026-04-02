from __future__ import annotations

import base64

from sqlalchemy.orm import Session as DbSession

from ..sessions.models import AuditEventRecord, AuditReceiptRecord, SealedNonceRecord


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


def get_latest_audit_receipt(db: DbSession, session_id: str) -> AuditReceiptRecord | None:
    return (
        db.query(AuditReceiptRecord)
        .filter(AuditReceiptRecord.session_id == session_id)
        .order_by(AuditReceiptRecord.created_at.desc())
        .first()
    )
