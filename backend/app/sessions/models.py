from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from ..db.database import Base
from .constants import SessionState


class Session(Base):
    __tablename__ = "verification_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, default=SessionState.CREATED, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    worker_phase = Column(String, nullable=True)
    lease_id = Column(String, nullable=True, index=True)
    lease_holder_id = Column(String, nullable=True)
    lease_acquired_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    version = Column(Integer, default=0, nullable=False)
    trust_outcome = Column(String, nullable=True)
    reason_codes = Column(JSON, default=list, nullable=False)
    connector_ids = Column(JSON, default=list, nullable=False)
    extraction_payload = Column(JSON, nullable=True)
    connector_payload = Column(JSON, nullable=True)
    document_profile_payload = Column(JSON, nullable=True)
    generalized_credentials_payload = Column(JSON, nullable=True)
    verification_plan_payload = Column(JSON, nullable=True)
    verification_task_results_payload = Column(JSON, nullable=True)
    credential_verification_bundles_payload = Column(JSON, nullable=True)
    verification_execution_summary_payload = Column(JSON, nullable=True)
    credential_audits_payload = Column(JSON, nullable=True)
    verification_summary_payload = Column(JSON, nullable=True)
    generalized_analysis_status = Column(String, nullable=True, default="NOT_STARTED")
    generalized_analysis_error = Column(Text, nullable=True)
    agent_document_understanding_payload = Column(JSON, nullable=True)
    agent_credential_candidates_payload = Column(JSON, nullable=True)
    agent_route_recommendations_payload = Column(JSON, nullable=True)
    agent_explanations_payload = Column(JSON, nullable=True)
    agent_run_summary_payload = Column(JSON, nullable=True)
    agent_run_status = Column(String, nullable=True, default="NOT_STARTED")
    agent_run_error = Column(Text, nullable=True)
    provider_execution_traces_payload = Column(JSON, nullable=True)
    provider_execution_status = Column(String, nullable=True, default="NOT_STARTED")
    provider_execution_error = Column(Text, nullable=True)
    verification_execution_status = Column(String, nullable=True, default="NOT_STARTED")
    verification_execution_error = Column(Text, nullable=True)
    document_commitment = Column(String, nullable=True)
    audit_receipt_id = Column(String, nullable=True)
    purge_status = Column(String, nullable=True)
    purge_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_at = Column(DateTime, nullable=True)
    verify_started_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UploadToken(Base):
    __tablename__ = "session_upload_tokens"

    token = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("verification_sessions.id"), nullable=False, index=True)
    is_used = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10), nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditReceiptRecord(Base):
    __tablename__ = "audit_receipts"

    audit_event_id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("verification_sessions.id"), nullable=False, index=True)
    reviewer_ref = Column(String, nullable=False)
    document_commitment = Column(String, nullable=False)
    trust_outcome = Column(String, nullable=False)
    reason_codes = Column(JSON, default=list, nullable=False)
    connector_ids = Column(JSON, default=list, nullable=False)
    issued_at = Column(DateTime, nullable=False)
    key_version = Column(String, nullable=False)
    receipt_hash = Column(String, nullable=False)
    signature = Column(String, nullable=True)
    hash_chain_prev = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    event_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("verification_sessions.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    event_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SealedNonceRecord(Base):
    __tablename__ = "sealed_nonces"

    nonce_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("verification_sessions.id"), nullable=False, index=True)
    nonce_value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class PurgeTrackingRecord(Base):
    __tablename__ = "purge_tracking"

    purge_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("verification_sessions.id"), nullable=False, index=True)
    purge_status = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
