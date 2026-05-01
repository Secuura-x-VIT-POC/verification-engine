import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.api.routes import router
from backend.app.auth.routes import get_current_user
from backend.app.db.database import Base, get_db
from backend.app.sessions.constants import SessionState
from backend.app.sessions.models import AuditReceiptRecord, Session as SessionModel
from backend.app.workflow.runtime import is_ready_for_cleanup
from backend.app.workflow.state_machine import validate_transition


class WorkflowApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_db] = self._override_get_db
        self.app.dependency_overrides[get_current_user] = lambda: "user-1"
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_status_endpoint_returns_processing_state(self):
        self._create_session(
            session_id="session-processing",
            status=SessionState.VERIFYING,
            user_id="user-1",
        )

        response = self.client.get("/session/session-processing/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-processing",
                "state": SessionState.VERIFYING,
                "processing": True,
                "retriable": False,
            },
        )

    def test_result_endpoint_returns_completed_trust_result(self):
        self._create_session(
            session_id="session-complete",
            status=SessionState.VERIFIED_GREEN,
            user_id="user-1",
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
        )

        response = self.client.get("/session/session-complete/result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-complete",
                "outcome": "GREEN",
                "reason_codes": ["CONNECTOR_VERIFIED"],
                "connector_ids": ["vit_registry"],
            },
        )

    def test_failed_session_returns_retriable_flag_correctly(self):
        self._create_session(
            session_id="session-failed",
            status=SessionState.FAILED_RETRIABLE,
            user_id="user-1",
            reason_codes=["EXTRACTION_CRASH"],
        )

        status_response = self.client.get("/session/session-failed/status")
        result_response = self.client.get("/session/session-failed/result")

        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.json()["retriable"])
        self.assertEqual(result_response.status_code, 200)
        self.assertEqual(result_response.json()["state"], SessionState.FAILED_RETRIABLE)
        self.assertTrue(result_response.json()["retriable"])
        self.assertIsNone(result_response.json()["outcome"])

    def test_result_endpoint_returns_safe_response_before_completion(self):
        self._create_session(
            session_id="session-pending",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.get("/session/session-pending/result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], SessionState.UPLOADED_PENDING_REVIEW)
        self.assertTrue("processing" in response.json())
        self.assertIsNone(response.json()["outcome"])

    def test_invalid_session_returns_404(self):
        response = self.client.get("/session/missing-session/status")
        self.assertEqual(response.status_code, 404)

    def test_is_ready_for_cleanup_returns_true_for_human_terminal_and_abandoned_states(self):
        verified_session = SessionModel(id="verified", user_id="user-1", status=SessionState.VERIFIED_AMBER)
        approved_session = SessionModel(id="approved", user_id="user-1", status=SessionState.HUMAN_APPROVED)
        failed_session = SessionModel(id="failed", user_id="user-1", status=SessionState.FAILED_PURGED)
        abandoned_session = SessionModel(id="abandoned", user_id="user-1", status=SessionState.ABANDONED_VERIFYING)
        active_session = SessionModel(id="active", user_id="user-1", status=SessionState.VERIFYING)

        self.assertFalse(is_ready_for_cleanup(verified_session))
        self.assertTrue(is_ready_for_cleanup(approved_session))
        self.assertTrue(is_ready_for_cleanup(failed_session))
        self.assertTrue(is_ready_for_cleanup(abandoned_session))
        self.assertFalse(is_ready_for_cleanup(active_session))

    def test_verified_green_can_move_to_pending_human_review(self):
        validate_transition(SessionState.VERIFIED_GREEN, SessionState.PENDING_HUMAN_REVIEW)

    def test_verifying_can_move_to_pending_human_review(self):
        validate_transition(SessionState.VERIFYING, SessionState.PENDING_HUMAN_REVIEW)

    def test_run_endpoint_starts_verification_and_returns_workspace_payload(self):
        file_path = self._create_temp_pdf()
        self._create_session(
            session_id="session-run-valid",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
            file_path=file_path,
        )

        with patch("backend.app.api.routes.start_verification", return_value="STARTED") as start_mock, patch(
            "backend.app.api.routes._build_workspace_payload",
            return_value=self._workspace_payload("session-run-valid"),
        ) as workspace_mock:
            response = self.client.post("/api/v1/verification-sessions/session-run-valid/run")

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.status_code, 410)
        self.assertEqual(response.json()["session_id"], "session-run-valid")
        self.assertIn("final_verdict", response.json())
        self.assertEqual(response.json()["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(response.json()["final_verdict"]["outcome"], "AMBER")
        start_mock.assert_called_once()
        self.assertEqual(start_mock.call_args.kwargs["worker_id"], "user-1")
        workspace_mock.assert_called_once()

    def test_run_endpoint_wrong_owner_returns_403(self):
        file_path = self._create_temp_pdf()
        self._create_session(
            session_id="session-run-other-user",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-2",
            file_path=file_path,
        )

        response = self.client.post("/api/v1/verification-sessions/session-run-other-user/run")

        self.assertEqual(response.status_code, 403)

    def test_run_endpoint_missing_file_path_returns_409(self):
        self._create_session(
            session_id="session-run-missing-file-path",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.post("/api/v1/verification-sessions/session-run-missing-file-path/run")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Upload a PDF before verification")

    def test_run_endpoint_missing_file_on_disk_returns_404(self):
        self._create_session(
            session_id="session-run-missing-file",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
            file_path=os.path.join(tempfile.gettempdir(), "secuura-missing-document.pdf"),
        )

        response = self.client.post("/api/v1/verification-sessions/session-run-missing-file/run")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Document not found on disk")

    def test_run_endpoint_cleanup_states_return_409(self):
        for state in (SessionState.PENDING_CLEANUP, SessionState.PURGE_COMPLETE, SessionState.FAILED_PURGED):
            with self.subTest(state=state):
                file_path = self._create_temp_pdf()
                session_id = f"session-run-{state.lower()}"
                self._create_session(
                    session_id=session_id,
                    status=state,
                    user_id="user-1",
                    file_path=file_path,
                )

                response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")

                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"], "Session is already closed")

    def test_run_endpoint_start_failed_returns_500(self):
        file_path = self._create_temp_pdf()
        self._create_session(
            session_id="session-run-start-failed",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
            file_path=file_path,
        )

        with patch("backend.app.api.routes.start_verification", return_value="FAILED"):
            response = self.client.post("/api/v1/verification-sessions/session-run-start-failed/run")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Verification could not be started")

    def test_review_decision_approve_returns_human_approved(self):
        self._create_session(
            session_id="session-review-approve",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-approve/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-review-approve",
                "status": SessionState.HUMAN_APPROVED,
                "final_decision": "APPROVED",
                "cleanup_ready": True,
                "audit_receipt_id": response.json()["audit_receipt_id"],
            },
        )
        self.assertTrue(response.json()["audit_receipt_id"])
        receipt = self._get_audit_receipt(response.json()["audit_receipt_id"])
        self.assertEqual(receipt.reviewer_decision, "APPROVED")
        self.assertIsNone(receipt.reviewer_note_hash)
        self.assertEqual(receipt.finding_counts, {"green": 1, "amber": 0, "red": 0})
        self.assertIsNotNone(receipt.approved_at)
        self.assertIsNone(receipt.rejected_at)
        self.assertIsNone(receipt.manual_review_at)

    def test_review_decision_reject_returns_human_rejected(self):
        self._create_session(
            session_id="session-review-reject",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            trust_outcome="RED",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-reject/review-decision",
            json={"decision": "REJECT"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.HUMAN_REJECTED)
        self.assertEqual(response.json()["final_decision"], "REJECTED")
        self.assertTrue(response.json()["cleanup_ready"])
        self.assertTrue(response.json()["audit_receipt_id"])
        receipt = self._get_audit_receipt(response.json()["audit_receipt_id"])
        self.assertEqual(receipt.reviewer_decision, "REJECTED")
        self.assertEqual(receipt.finding_counts, {"green": 0, "amber": 0, "red": 1})
        self.assertIsNotNone(receipt.rejected_at)
        self.assertIsNone(receipt.approved_at)
        self.assertIsNone(receipt.manual_review_at)

    def test_review_decision_manual_review_returns_manual_review_required(self):
        reviewer_note = "Needs secondary review for the uploaded credential"
        self._create_session(
            session_id="session-review-manual",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            verification_execution_summary_payload={
                "summary": {
                    "green_count": 2,
                    "amber_count": 1,
                    "red_count": 0,
                    "student_name": "Alice Rao",
                }
            },
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-manual/review-decision",
            json={"decision": "NEEDS_MANUAL_REVIEW", "reviewer_note": reviewer_note},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.MANUAL_REVIEW_REQUIRED)
        self.assertEqual(response.json()["final_decision"], "MANUAL_REVIEW_REQUIRED")
        self.assertTrue(response.json()["cleanup_ready"])
        self.assertTrue(response.json()["audit_receipt_id"])
        receipt = self._get_audit_receipt(response.json()["audit_receipt_id"])
        self.assertEqual(receipt.reviewer_decision, "MANUAL_REVIEW_REQUIRED")
        self.assertIsNotNone(receipt.reviewer_note_hash)
        self.assertNotEqual(receipt.reviewer_note_hash, reviewer_note)
        self.assertNotIn(reviewer_note, str(receipt.__dict__))
        self.assertEqual(receipt.finding_counts, {"green": 2, "amber": 1, "red": 0})
        self.assertNotIn("Alice Rao", str(receipt.finding_counts))
        self.assertIsNotNone(receipt.manual_review_at)
        self.assertIsNone(receipt.approved_at)
        self.assertIsNone(receipt.rejected_at)

    def test_review_decision_allows_verified_green_compatibility_path(self):
        self._create_session(
            session_id="session-review-verified",
            status=SessionState.VERIFIED_GREEN,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-verified/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.HUMAN_APPROVED)
        self.assertTrue(response.json()["audit_receipt_id"])

    def test_review_decision_verifying_returns_409(self):
        self._create_session(
            session_id="session-review-verifying",
            status=SessionState.VERIFYING,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-verifying/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 409)

    def test_review_decision_uploaded_pending_review_returns_409(self):
        self._create_session(
            session_id="session-review-uploaded",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-uploaded/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 409)

    def test_review_decision_wrong_owner_returns_403(self):
        self._create_session(
            session_id="session-review-other-user",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-2",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-other-user/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 403)

    def test_review_decision_invalid_decision_returns_422(self):
        self._create_session(
            session_id="session-review-invalid",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-invalid/review-decision",
            json={"decision": "MAYBE"},
        )

        self.assertEqual(response.status_code, 422)

    def test_review_decision_updates_existing_audit_receipt(self):
        self._create_session(
            session_id="session-review-existing-audit",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            audit_receipt_id="audit-existing",
        )
        self._create_audit_receipt("audit-existing", "session-review-existing-audit")

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-existing-audit/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit_receipt_id"], "audit-existing")
        receipt = self._get_audit_receipt("audit-existing")
        self.assertEqual(receipt.reviewer_decision, "APPROVED")
        self.assertEqual(receipt.finding_counts, {"green": 0, "amber": 0, "red": 0, "unknown": True})
        self.assertNotEqual(receipt.receipt_hash, "old-hash")

    def test_review_decision_manual_review_requires_note(self):
        self._create_session(
            session_id="session-review-manual-no-note",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-manual-no-note/review-decision",
            json={"decision": "NEEDS_MANUAL_REVIEW"},
        )

        self.assertEqual(response.status_code, 422)

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _create_session(
        self,
        *,
        session_id: str,
        status: str,
        user_id: str,
        trust_outcome: str | None = None,
        reason_codes: list[str] | None = None,
        connector_ids: list[str] | None = None,
        file_path: str | None = None,
        verification_execution_summary_payload: dict | None = None,
        audit_receipt_id: str | None = None,
    ) -> None:
        db = self.SessionLocal()
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            status=status,
            file_path=file_path,
            filename="demo.pdf" if file_path else None,
            trust_outcome=trust_outcome,
            reason_codes=reason_codes or [],
            connector_ids=connector_ids or [],
            verification_execution_summary_payload=verification_execution_summary_payload,
            audit_receipt_id=audit_receipt_id,
        )
        db.add(session)
        db.commit()
        db.close()

    def _create_audit_receipt(self, audit_event_id: str, session_id: str) -> None:
        db = self.SessionLocal()
        receipt = AuditReceiptRecord(
            audit_event_id=audit_event_id,
            session_id=session_id,
            reviewer_ref="worker-1",
            document_commitment="commitment-1",
            trust_outcome="GREEN",
            reason_codes=[],
            connector_ids=[],
            issued_at=datetime.utcnow(),
            key_version="v1",
            receipt_hash="old-hash",
        )
        db.add(receipt)
        db.commit()
        db.close()

    def _get_audit_receipt(self, audit_event_id: str) -> AuditReceiptRecord:
        db = self.SessionLocal()
        try:
            receipt = db.query(AuditReceiptRecord).filter(AuditReceiptRecord.audit_event_id == audit_event_id).first()
            self.assertIsNotNone(receipt)
            db.expunge(receipt)
            return receipt
        finally:
            db.close()

    def _create_temp_pdf(self) -> str:
        file_handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        file_handle.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
        file_handle.close()
        self.addCleanup(lambda: os.path.exists(file_handle.name) and os.remove(file_handle.name))
        return file_handle.name

    def _workspace_payload(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "status": SessionState.PENDING_HUMAN_REVIEW,
            "ui_status": "Ready for human review",
            "document": {
                "filename": "demo.pdf",
                "document_type": "academic_credential",
                "page_count": 1,
                "used_ocr": False,
                "warnings": [],
                "highlights_count": 0,
            },
            "summary": {
                "total_fields": 0,
                "green_count": 0,
                "amber_count": 0,
                "red_count": 0,
                "matching_score": 0.0,
                "visual_match_probability": 0.0,
                "risk_level": "MEDIUM",
                "active_exceptions": [],
            },
            "fields": [],
            "verifiers": [],
            "final_verdict": {
                "outcome": "AMBER",
                "reason_codes": [],
                "connector_ids": [],
                "explanation": "",
                "risk_level": "MEDIUM",
                "matching_score": 0.0,
                "visual_match_probability": 0.0,
            },
            "audit": [],
            "actions": [],
        }


if __name__ == "__main__":
    unittest.main()
