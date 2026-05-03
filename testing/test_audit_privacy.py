import json
import os
import sys
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.audit.hmac_utils import generate_nonce  # noqa: E402
from backend.app.audit.service import (  # noqa: E402
    serialize_audit_summary,
    store_audit_bundle,
    upsert_final_review_receipt,
)
from backend.app.db.database import Base  # noqa: E402
from backend.app.sessions.constants import SessionState  # noqa: E402
from backend.app.sessions.models import AuditEventRecord, AuditReceiptRecord, Session as SessionModel  # noqa: E402


class AuditPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def test_final_review_receipt_hashes_note_and_keeps_counts_only(self):
        db = self.SessionLocal()
        try:
            session = SessionModel(
                id="audit-privacy-session",
                user_id="reviewer-1",
                status=SessionState.PENDING_HUMAN_REVIEW,
                trust_outcome="AMBER",
                reason_codes=["NO_VERIFIER_EVIDENCE"],
                connector_ids=["manual_review"],
                document_commitment="sha256:commitment",
                workspace_payload={
                    "summary": {
                        "green_count": 1,
                        "amber_count": 2,
                        "red_count": 0,
                        "raw_name": "RAW_NAME_SENTINEL_PERSON_E",
                    }
                },
            )
            db.add(session)
            db.commit()

            reviewer_note = "RAW_REVIEWER_NOTE_SENTINEL_PERSON_E"
            receipt = upsert_final_review_receipt(
                db,
                session,
                reviewer_ref="reviewer-1",
                reviewer_decision="MANUAL_REVIEW_REQUIRED",
                reviewer_note=reviewer_note,
            )
            db.commit()

            summary = serialize_audit_summary(receipt, cleanup_status="PURGE_COMPLETE")
            serialized = json.dumps(
                {
                    "summary": summary,
                    "receipt": receipt.__dict__,
                    "events": [event.event_data for event in db.query(AuditEventRecord).all()],
                },
                sort_keys=True,
                default=str,
            )

            self.assertEqual(summary["overall_outcome"], "AMBER")
            self.assertEqual(summary["reviewer_decision"], "MANUAL_REVIEW_REQUIRED")
            self.assertEqual(summary["finding_counts"], {"green": 1, "amber": 2, "red": 0})
            self.assertIsNotNone(summary["reviewer_note_hash"])
            self.assertNotIn(reviewer_note, serialized)
            self.assertNotIn("RAW_NAME_SENTINEL_PERSON_E", serialized)
        finally:
            db.close()

    def test_store_audit_bundle_strips_unsafe_event_keys(self):
        db = self.SessionLocal()
        try:
            receipt = {
                "audit_event_id": "audit-event-1",
                "session_id": "audit-session-1",
                "reviewer_ref": "reviewer-1",
                "document_commitment": "sha256:commitment",
                "trust_outcome": "GREEN",
                "reason_codes": ["ALL_REQUIRED_CHECKS_MATCHED"],
                "connector_ids": ["local_mock"],
                "issued_at": datetime.utcnow(),
                "key_version": "v1",
                "receipt_hash": "receipt-hash",
                "raw_text": "RAW_TEXT_SENTINEL_PERSON_E",
                "reviewer_note": "RAW_REVIEWER_NOTE_SENTINEL_PERSON_E",
            }

            store_audit_bundle(db, receipt, generate_nonce())
            db.commit()

            persisted = db.query(AuditReceiptRecord).one()
            events = db.query(AuditEventRecord).all()
            serialized = json.dumps(
                {"receipt": persisted.__dict__, "events": [event.event_data for event in events]},
                sort_keys=True,
                default=str,
            )
            self.assertNotIn("RAW_TEXT_SENTINEL_PERSON_E", serialized)
            self.assertNotIn("RAW_REVIEWER_NOTE_SENTINEL_PERSON_E", serialized)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
