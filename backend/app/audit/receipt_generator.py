import uuid
from datetime import datetime


def generate_receipt(
    session_id: str,
    reviewer_ref: str,
    commitment: str,
    trust_result: dict,
    key_version: str = "v1"
):
    issued_at = datetime.utcnow()

    receipt_hash = commitment  # can extend later

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
    }