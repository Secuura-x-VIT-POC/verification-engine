from __future__ import annotations

import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./secuura.db")
CONNECT_ARGS = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
LOGGER = logging.getLogger(__name__)

engine = create_engine(DATABASE_URL, connect_args=CONNECT_ARGS)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()

SESSION_TABLE_NAME = "verification_sessions"
AUDIT_RECEIPT_TABLE_NAME = "audit_receipts"
SESSION_SCHEMA_UPDATES = {
    "worker_phase": "VARCHAR",
    "lease_id": "VARCHAR",
    "lease_holder_id": "VARCHAR",
    "lease_acquired_at": "TIMESTAMP",
    "heartbeat_at": "TIMESTAMP",
    "version": "INTEGER NOT NULL DEFAULT 0",
    "trust_outcome": "VARCHAR",
    "reason_codes": "JSON NOT NULL DEFAULT '[]'",
    "connector_ids": "JSON NOT NULL DEFAULT '[]'",
    "extraction_payload": "JSON",
    "connector_payload": "JSON",
    "document_profile_payload": "JSON",
    "generalized_credentials_payload": "JSON",
    "verification_plan_payload": "JSON",
    "verification_task_results_payload": "JSON",
    "credential_verification_bundles_payload": "JSON",
    "verification_execution_summary_payload": "JSON",
    "credential_audits_payload": "JSON",
    "verification_summary_payload": "JSON",
    "generalized_analysis_status": "VARCHAR",
    "generalized_analysis_error": "TEXT",
    "agent_document_understanding_payload": "JSON",
    "agent_credential_candidates_payload": "JSON",
    "agent_route_recommendations_payload": "JSON",
    "agent_explanations_payload": "JSON",
    "agent_run_summary_payload": "JSON",
    "agent_run_status": "VARCHAR",
    "agent_run_error": "TEXT",
    "provider_execution_traces_payload": "JSON",
    "provider_execution_status": "VARCHAR",
    "provider_execution_error": "TEXT",
    "provider_operating_mode": "VARCHAR",
    "demo_profile_key": "VARCHAR",
    "execution_environment_label": "VARCHAR",
    "provider_transition_notes": "JSON",
    "verification_execution_status": "VARCHAR",
    "verification_execution_error": "TEXT",
    "document_commitment": "VARCHAR",
    "audit_receipt_id": "VARCHAR",
    "workspace_payload": "JSON",
    "purge_status": "VARCHAR",
    "purge_error": "TEXT",
    "uploaded_at": "TIMESTAMP",
    "verify_started_at": "TIMESTAMP",
    "verified_at": "TIMESTAMP",
    "closed_at": "TIMESTAMP",
    "updated_at": "TIMESTAMP",
}
AUDIT_RECEIPT_SCHEMA_UPDATES = {
    "reviewer_decision": "VARCHAR",
    "reviewer_note_hash": "VARCHAR",
    "finding_counts": "JSON",
    "approved_at": "TIMESTAMP",
    "rejected_at": "TIMESTAMP",
    "manual_review_at": "TIMESTAMP",
}


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from ..auth import models as _auth_models  # noqa: F401
    from ..sessions import models as _session_models  # noqa: F401
    from ..workflow import job_queue as _workflow_job_queue  # noqa: F401

    Base.metadata.create_all(bind=engine)
    sync_existing_schema(engine)


def sync_existing_schema(bind) -> None:
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    _sync_table_columns(
        bind,
        inspector,
        table_names,
        SESSION_TABLE_NAME,
        SESSION_SCHEMA_UPDATES,
    )
    _sync_table_columns(
        bind,
        inspector,
        table_names,
        AUDIT_RECEIPT_TABLE_NAME,
        AUDIT_RECEIPT_SCHEMA_UPDATES,
    )


def _sync_table_columns(bind, inspector, table_names: set[str], table_name: str, schema_updates: dict[str, str]) -> None:
    if table_name not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = [
        (column_name, definition)
        for column_name, definition in schema_updates.items()
        if column_name not in existing_columns
    ]

    with bind.begin() as connection:
        for column_name, definition in missing_columns:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
            )
            LOGGER.info(
                "DB_SCHEMA_SYNC table=%s added_column=%s",
                table_name,
                column_name,
            )
