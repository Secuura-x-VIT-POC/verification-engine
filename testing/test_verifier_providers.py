import json
import os
import sys
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from backend.app.sessions.models import Session as SessionModel
from backend.app.verification_domain.contracts import (
    BoundingBox,
    ExtractedCredential,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    VerifierRouteDecision,
)
from backend.app.verifier_execution.service import build_and_persist_execution_artifacts, build_execution_artifacts
from backend.app.verifier_providers.http_client import SafeHttpClientError, SafeHttpJsonClient
from backend.app.verifier_providers.policies import minimize_payload
from backend.app.verifier_providers.registry import build_default_provider_registry


class _ProviderHandler(BaseHTTPRequestHandler):
    response_payload = {
        "matched_fields": {"name": "Kanak Sharma"},
        "reason_codes": ["HTTP_PROVIDER_MATCH"],
        "confidence": 0.99,
        "response_summary": {"source": "identity-http-fixture"},
    }

    def do_POST(self):  # noqa: N802
        if self.path != "/verify/identity":
            self.send_response(404)
            self.end_headers()
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw.decode("utf-8"))
        if "value" not in payload:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"message":"missing value"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.response_payload).encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A003
        return


class ProviderRegistryTests(unittest.TestCase):
    def test_default_provider_registry_exposes_local_mock_capability(self):
        registry = build_default_provider_registry()

        provider = registry.find_provider(verifier_key="identity_db", category="identity")

        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider_key, "local_mock")


class ProviderPolicyTests(unittest.TestCase):
    def test_minimize_payload_redacts_document_like_content(self):
        minimized, redaction_applied = minimize_payload(
            {
                "value": "Kanak Sharma",
                "source_text": "Kanak Sharma from the full document body",
                "document_text": "x" * 500,
            },
            allow_document_upload=False,
        )

        self.assertTrue(redaction_applied)
        self.assertEqual(minimized["source_text"], "[redacted]")
        self.assertEqual(minimized["document_text"], "[redacted]")
        self.assertEqual(minimized["value"], "Kanak Sharma")


class SafeHttpClientTests(unittest.TestCase):
    def test_http_client_blocks_non_allowlisted_domains(self):
        client = SafeHttpJsonClient(
            request_size_limit_bytes=1024,
            response_size_limit_bytes=1024,
        )

        with self.assertRaises(SafeHttpClientError) as exc:
            client.post_json(
                url="https://example.com/verify",
                payload={"value": "x"},
                headers={},
                timeout_ms=100,
                retry_budget=0,
                domain_allowlist=("127.0.0.1",),
            )

        self.assertEqual(exc.exception.code, "blocked_domain")


class ProviderBackedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_thread.join(timeout=2)

    def test_execution_uses_http_provider_when_enabled(self):
        credentials, plan = self._build_identity_inputs()
        base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        with patch.dict(
            os.environ,
            {
                "VERIFIER_EXTERNAL_PROVIDER_ENABLED": "1",
                "VERIFIER_ENABLED_PROVIDERS": "identity_http,local_mock",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_ENABLED": "1",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_BASE_URL": base_url,
            },
            clear=False,
        ):
            artifacts = build_execution_artifacts(
                "provider-http-session",
                {"document_type": "identity_document"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.audit_status, "VERIFIED")
        self.assertEqual(result.raw_result_summary["provider_key"], "identity_http")
        self.assertEqual(result.raw_result_summary["provider_technical_status"], "SUCCESS")
        self.assertEqual(artifacts["provider_execution_status"], "READY")
        self.assertEqual(trace.provider_key, "identity_http")
        self.assertFalse(trace.fallback_used)

    def test_execution_falls_back_safely_when_provider_domain_is_blocked(self):
        credentials, plan = self._build_identity_inputs()
        base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        with patch.dict(
            os.environ,
            {
                "VERIFIER_EXTERNAL_PROVIDER_ENABLED": "1",
                "VERIFIER_ENABLED_PROVIDERS": "identity_http,local_mock",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_ENABLED": "1",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_BASE_URL": base_url,
                "VERIFIER_PROVIDER_IDENTITY_HTTP_DOMAIN_ALLOWLIST": "example.com",
            },
            clear=False,
        ):
            artifacts = build_execution_artifacts(
                "provider-blocked-session",
                {"document_type": "identity_document"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.audit_status, "PARTIAL")
        self.assertTrue(result.raw_result_summary["provider_fallback_used"])
        self.assertEqual(result.raw_result_summary["provider_key"], "identity_http")
        self.assertEqual(trace.technical_status, "FAILED")
        self.assertTrue(trace.fallback_used)

    @staticmethod
    def _build_identity_inputs():
        credentials = SessionCredentialCollection(
            session_id="provider-http-session",
            document_type="identity_document",
            credentials=[
                ExtractedCredential(
                    credential_id="name-1",
                    label="Candidate Name",
                    category="identity",
                    value="Kanak Sharma",
                    normalized_value="Kanak Sharma",
                    confidence=0.98,
                    page=1,
                    bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=40, y1=20),
                    requires_verification=True,
                )
            ],
        )
        plan = SessionVerificationPlan(
            session_id="provider-http-session",
            document_type="identity_document",
            route_decisions=[
                VerifierRouteDecision(
                    credential_id="name-1",
                    selected_verifier_key="identity_db",
                    selected_verifier_label="Identity Database",
                    route_reason="identity",
                )
            ],
            tasks=[
                VerificationTask(
                    task_id="task-name-1",
                    credential_id="name-1",
                    verifier_key="identity_db",
                    verifier_label="Identity Database",
                    verification_type="identity",
                    required=True,
                    status="PLANNED",
                    input_payload={"label": "Candidate Name", "value": "Kanak Sharma"},
                )
            ],
        )
        return credentials, plan


class ProviderPersistenceAndApiTests(unittest.TestCase):
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

    def test_provider_traces_persist_without_full_raw_payloads(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="provider-persisted-session",
            user_id="user-1",
            status=SessionState.VERIFYING,
            extraction_payload={
                "document_type": "identity_document",
                "field_details": [
                    {
                        "key": "name",
                        "label": "Candidate Name",
                        "value": "Kanak Sharma",
                        "confidence": 0.98,
                        "bounding_boxes": [{"page": 1, "x0": 10, "y0": 10, "x1": 40, "y1": 20}],
                    }
                ],
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        build_and_persist_execution_artifacts(session)
        db.commit()
        db.refresh(session)

        self.assertEqual(session.provider_execution_status, "READY")
        self.assertIsNotNone(session.provider_execution_traces_payload)
        trace_payload = session.provider_execution_traces_payload["traces"][0]
        self.assertNotIn("input_payload", trace_payload)
        self.assertNotIn("redacted_payload", trace_payload)
        db.close()

    def test_provider_endpoints_return_safe_empty_structures_for_old_sessions(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="provider-empty-session",
            user_id="user-1",
            status=SessionState.CREATED,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.close()

        traces_response = self.client.get("/session/provider-empty-session/provider-execution-traces")
        status_response = self.client.get("/session/provider-empty-session/provider-execution-status")
        capabilities_response = self.client.get("/session/provider-empty-session/provider-capabilities")

        self.assertEqual(traces_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(capabilities_response.status_code, 200)
        self.assertEqual(traces_response.json()["traces"], [])
        self.assertEqual(status_response.json()["provider_execution_status"], "NOT_STARTED")
        self.assertTrue(any(cap["provider_key"] == "local_mock" for cap in capabilities_response.json()["capabilities"]))

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
