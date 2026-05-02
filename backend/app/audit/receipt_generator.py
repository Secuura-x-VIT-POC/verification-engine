import json
import uuid
from datetime import datetime

from .hmac_utils import generate_hmac_hex


def generate_receipt(
    session_id: str,
    reviewer_ref: str,
    commitment: str,
    trust_result: dict,
    key_version: str = "v1"
):
    issued_at = datetime.utcnow()

    receipt_hash = _build_receipt_hash(
        session_id=session_id,
        document_commitment=commitment,
        trust_outcome=trust_result["outcome"],
        reviewer_decision=trust_result.get("reviewer_decision"),
        reviewer_note_hash=trust_result.get("reviewer_note_hash"),
        finding_counts=trust_result.get("finding_counts"),
        issued_at=issued_at,
    )

    return {
        "audit_event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "reviewer_ref": reviewer_ref,
        "document_commitment": commitment,
        "trust_outcome": trust_result["outcome"],
        "reason_codes": trust_result["reason_codes"],
        "connector_ids": trust_result.get("connector_ids", []),
        "issued_at": issued_at,
        "key_version": key_version,
        "receipt_hash": receipt_hash,
        "reviewer_decision": trust_result.get("reviewer_decision"),
        "reviewer_note_hash": trust_result.get("reviewer_note_hash"),
        "finding_counts": trust_result.get("finding_counts"),
    }


def _build_receipt_hash(
    *,
    session_id: str,
    document_commitment: str,
    trust_outcome: str,
    reviewer_decision: str | None = None,
    reviewer_note_hash: str | None = None,
    finding_counts: dict | None = None,
    issued_at: datetime | None = None,
) -> str:
    payload = {
        "session_id": session_id,
        "document_commitment": document_commitment,
        "trust_outcome": trust_outcome,
        "reviewer_decision": reviewer_decision,
        "reviewer_note_hash": reviewer_note_hash,
        "finding_counts": finding_counts or {},
        "issued_at": issued_at.isoformat() if issued_at else None,
    }
    return generate_hmac_hex(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
