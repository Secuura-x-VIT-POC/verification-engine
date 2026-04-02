import os
import sys
import unittest

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
from backend.app.sessions.models import Session as SessionModel
from backend.app.workflow.runtime import is_ready_for_cleanup


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

    def test_is_ready_for_cleanup_returns_true_for_terminal_and_abandoned_states(self):
        verified_session = SessionModel(id="verified", user_id="user-1", status=SessionState.VERIFIED_AMBER)
        failed_session = SessionModel(id="failed", user_id="user-1", status=SessionState.FAILED_PURGED)
        abandoned_session = SessionModel(id="abandoned", user_id="user-1", status=SessionState.ABANDONED_VERIFYING)
        active_session = SessionModel(id="active", user_id="user-1", status=SessionState.VERIFYING)

        self.assertTrue(is_ready_for_cleanup(verified_session))
        self.assertTrue(is_ready_for_cleanup(failed_session))
        self.assertTrue(is_ready_for_cleanup(abandoned_session))
        self.assertFalse(is_ready_for_cleanup(active_session))

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
    ) -> None:
        db = self.SessionLocal()
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            status=status,
            trust_outcome=trust_outcome,
            reason_codes=reason_codes or [],
            connector_ids=connector_ids or [],
        )
        db.add(session)
        db.commit()
        db.close()


if __name__ == "__main__":
    unittest.main()
