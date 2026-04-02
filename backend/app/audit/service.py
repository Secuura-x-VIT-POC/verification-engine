import os
import uuid

from sqlalchemy import create_engine, text


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is not set.")
        _engine = create_engine(database_url)
    return _engine


def store_audit_bundle(receipt: dict, nonce: bytes):
    with get_engine().begin() as conn:

        # 1. audit_receipts
        conn.execute(text("""
            INSERT INTO audit.audit_receipts (
                audit_event_id,
                session_id,
                reviewer_ref,
                document_commitment,
                trust_outcome,
                reason_codes,
                connector_ids,
                issued_at,
                key_version,
                receipt_hash
            ) VALUES (
                :audit_event_id,
                :session_id,
                :reviewer_ref,
                :document_commitment,
                :trust_outcome,
                :reason_codes,
                :connector_ids,
                :issued_at,
                :key_version,
                :receipt_hash
            )
        """), receipt)

        # 2. sealed_nonces (encrypted later)
        conn.execute(text("""
            INSERT INTO audit.sealed_nonces (
                nonce_id,
                session_id,
                nonce_value
            ) VALUES (
                :nonce_id,
                :session_id,
                :nonce_value
            )
        """), {
            "nonce_id": str(uuid.uuid4()),
            "session_id": receipt["session_id"],
            "nonce_value": nonce
        })

        # 3. audit_events
        conn.execute(text("""
            INSERT INTO audit.audit_events (
                event_id,
                session_id,
                event_type,
                event_data
            ) VALUES (
                :event_id,
                :session_id,
                'AUDIT_RECEIPT_ISSUED',
                :event_data
            )
        """), {
            "event_id": str(uuid.uuid4()),
            "session_id": receipt["session_id"],
            "event_data": str(receipt)
        })
