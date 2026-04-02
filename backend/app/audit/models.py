from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime


class TrustResult(BaseModel):
    outcome: str
    reason_codes: List[str]
    connector_ids: List[str]


class AuditReceipt(BaseModel):
    audit_event_id: UUID
    session_id: UUID
    reviewer_ref: str

    document_commitment: str

    trust_outcome: str
    reason_codes: List[str]
    connector_ids: Optional[List[str]]

    issued_at: datetime

    key_version: str
    receipt_hash: str
    signature: Optional[str]

    hash_chain_prev: Optional[str]
    created_at: Optional[datetime]


class AuditEvent(BaseModel):
    event_id: UUID
    session_id: UUID
    event_type: str
    event_data: Optional[dict]
    created_at: Optional[datetime]


class SealedNonce(BaseModel):
    nonce_id: UUID
    session_id: UUID
    nonce_value: bytes
    created_at: Optional[datetime]
    is_active: bool = True


class PurgeTracking(BaseModel):
    purge_id: UUID
    session_id: UUID
    purge_status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]