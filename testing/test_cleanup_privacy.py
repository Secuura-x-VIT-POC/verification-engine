import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.db.database import Base  # noqa: E402
from backend.app.sessions.constants import SessionState  # noqa: E402
from backend.app.sessions.models import AuditReceiptRecord, Session as SessionModel  # noqa: E402
from backend.app.workflow.runtime import close_session  # noqa: E402


class CleanupPrivacyTests(unittest.TestCase):
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

    def test_close_session_deletes_file_clears_workspace_and_keeps_audit(self):
        document_path = Path(os.getcwd()) / "person_e_cleanup_test_document.pdf"
        if document_path.exists():
            document_path.unlink()
        self.addCleanup(lambda: document_path.exists() and document_path.unlink())
        document_path.write_bytes(b"%PDF-1.7\n%%EOF")
        db = self.SessionLocal()
        try:
            session = SessionModel(
                id="cleanup-privacy-session",
                user_id="reviewer-1",
                status=SessionState.HUMAN_APPROVED,
                filename="document.pdf",
                file_path=str(document_path),
                trust_outcome="GREEN",
                reason_codes=["ALL_REQUIRED_CHECKS_MATCHED"],
                connector_ids=["local_mock"],
                document_commitment="sha256:commitment",
                audit_receipt_id="audit-cleanup-1",
                workspace_payload={"raw_text": "RAW_TEXT_SENTINEL_PERSON_E", "display_value": "RAW_ID_NUMBER_SENTINEL_PERSON_E"},
                extraction_payload={"raw_text": "RAW_OCR_SENTINEL_PERSON_E"},
                connector_payload={"response_body": "RAW_PROVIDER_SENTINEL_PERSON_E"},
                agent_run_summary_payload={"gemini_response": "RAW_GEMINI_SENTINEL_PERSON_E"},
                provider_execution_traces_payload={"raw_response": "RAW_PROVIDER_SENTINEL_PERSON_E"},
            )
            receipt = AuditReceiptRecord(
                audit_event_id="audit-cleanup-1",
                session_id=session.id,
                reviewer_ref="reviewer-1",
                document_commitment="sha256:commitment",
                trust_outcome="GREEN",
                reason_codes=["ALL_REQUIRED_CHECKS_MATCHED"],
                connector_ids=["local_mock"],
                issued_at=datetime.utcnow(),
                key_version="v1",
                receipt_hash="receipt-hash",
                reviewer_decision="APPROVED",
                finding_counts={"green": 1, "amber": 0, "red": 0},
            )
            db.add(session)
            db.add(receipt)
            db.commit()

            closed = close_session(db, session)

            self.assertEqual(closed.status, SessionState.PURGE_COMPLETE)
            self.assertFalse(document_path.exists())
            self.assertIsNone(closed.file_path)
            self.assertIsNone(closed.filename)
            self.assertIsNone(closed.workspace_payload)
            self.assertIsNone(closed.extraction_payload)
            self.assertIsNone(closed.connector_payload)
            self.assertIsNone(closed.agent_run_summary_payload)
            self.assertIsNone(closed.provider_execution_traces_payload)
            self.assertEqual(closed.document_commitment, "sha256:commitment")
            self.assertEqual(closed.audit_receipt_id, "audit-cleanup-1")
            self.assertIsNotNone(db.query(AuditReceiptRecord).filter_by(audit_event_id="audit-cleanup-1").first())

            serialized = json.dumps(closed.__dict__, sort_keys=True, default=str)
            for sentinel in {
                "RAW_TEXT_SENTINEL_PERSON_E",
                "RAW_ID_NUMBER_SENTINEL_PERSON_E",
                "RAW_OCR_SENTINEL_PERSON_E",
                "RAW_GEMINI_SENTINEL_PERSON_E",
                "RAW_PROVIDER_SENTINEL_PERSON_E",
            }:
                self.assertNotIn(sentinel, serialized)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
