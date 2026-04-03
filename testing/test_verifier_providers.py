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
    FALLBACK_REASON_ENTRA_NOT_CONFIGURED,
    FALLBACK_REASON_PROVIDER_ATTEMPT_FAILED,
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
    identity_response_payload = {
        "matched_fields": {"name": "Kanak Sharma"},
        "reason_codes": ["HTTP_PROVIDER_MATCH"],
        "confidence": 0.99,
        "response_summary": {"source": "identity-http-fixture"},
    }
    entra_response_payload = {
        "verified_claims": {"name": "Kanak Sharma"},
        "reason_codes": ["ENTRA_VERIFIED_ID_MATCH"],
        "confidence": 0.99,
        "presentation_summary": {"source": "entra-fixture", "presentation_state": "verified"},
    }

    def do_POST(self):  # noqa: N802
        if self.path not in {"/verify/identity", "/presentations/verify"}:
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
        response_payload = (
            self.entra_response_payload
            if self.path == "/presentations/verify"
            else self.identity_response_payload
        )
        self.wfile.write(json.dumps(response_payload).encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A003
        return


class ProviderRegistryTests(unittest.TestCase):
    def test_default_provider_registry_exposes_local_mock_capability(self):
        registry = build_default_provider_registry()

        provider = registry.find_provider(verifier_key="identity_db", category="identity")

        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider_key, "local_mock")

    def test_registry_exposes_entra_demo_provider_when_demo_mode_is_enabled(self):
        with patch.dict(
            os.environ,
            {
                "VERIFIER_PROVIDER_OPERATING_MODE": "DEMO_MOCK",
            },
            clear=False,
        ):
            registry = build_default_provider_registry()

        provider = registry.find_provider(
            verifier_key="identity_db",
            category="identity",
            preferred_provider_key="entra_verified_id",
        )

        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider_key, "entra_verified_id")

    def test_registry_prefers_entra_verified_id_when_enabled(self):
        with patch.dict(
            os.environ,
            {
                "VERIFIER_EXTERNAL_PROVIDER_ENABLED": "1",
                "VERIFIER_ENABLED_PROVIDERS": "entra_verified_id,identity_http,local_mock",
                "VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_ENABLED": "1",
                "VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_BASE_URL": "https://entra.example.com",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_ENABLED": "1",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_BASE_URL": "https://identity.example.com",
            },
            clear=False,
        ):
            registry = build_default_provider_registry()

        provider = registry.find_provider(
            verifier_key="identity_db",
            category="identity",
            preferred_provider_key="entra_verified_id",
        )

        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider_key, "entra_verified_id")


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

    def test_execution_prefers_entra_verified_id_when_enabled(self):
        credentials, plan = self._build_identity_inputs(preferred_provider_key="entra_verified_id")
        base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        with patch.dict(
            os.environ,
            {
                "VERIFIER_EXTERNAL_PROVIDER_ENABLED": "1",
                "VERIFIER_ENABLED_PROVIDERS": "entra_verified_id,identity_http,local_mock",
                "VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_ENABLED": "1",
                "VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_BASE_URL": base_url,
                "VERIFIER_PROVIDER_IDENTITY_HTTP_ENABLED": "1",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_BASE_URL": base_url,
            },
            clear=False,
        ):
            artifacts = build_execution_artifacts(
                "provider-entra-session",
                {"document_type": "identity_document"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.audit_status, "VERIFIED")
        self.assertEqual(result.raw_result_summary["provider_key"], "entra_verified_id")
        self.assertEqual(result.raw_result_summary["provider_label"], "Microsoft Entra Verified ID")
        self.assertEqual(trace.provider_key, "entra_verified_id")
        self.assertEqual(trace.response_summary["trust_rail"], "Microsoft Entra Verified ID")

    def test_execution_uses_seeded_entra_demo_mode_when_explicitly_enabled(self):
        credentials, plan = self._build_identity_inputs(
            preferred_provider_key="entra_verified_id",
            planned_provider_key="entra_verified_id",
            planned_execution_mode="DEMO_PROVIDER",
        )

        with patch.dict(
            os.environ,
            {
                "VERIFIER_PROVIDER_OPERATING_MODE": "DEMO_MOCK",
                "VERIFIER_DEMO_PROFILE_KEY": "identity_mismatch_demo",
            },
            clear=False,
        ):
            artifacts = build_execution_artifacts(
                "provider-demo-session",
                {"document_type": "identity_document"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.raw_result_summary["provider_key"], "entra_verified_id")
        self.assertEqual(result.raw_result_summary["provider_operating_mode"], "DEMO_MOCK")
        self.assertTrue(result.raw_result_summary["provider_is_demo_result"])
        self.assertEqual(trace.provider_operating_mode, "DEMO_MOCK")
        self.assertEqual(trace.demo_profile_key, "identity_mismatch_demo")
        self.assertEqual(trace.outbound_mode, "LOCAL_ONLY")
        self.assertEqual(artifacts["provider_operating_mode"], "DEMO_MOCK")
        self.assertEqual(artifacts["demo_profile_key"], "identity_mismatch_demo")

    def test_execution_can_use_supplementary_demo_provider_when_planned(self):
        credentials = SessionCredentialCollection(
            session_id="provider-demo-academic",
            document_type="academic_credential",
            credentials=[
                ExtractedCredential(
                    credential_id="credential-1",
                    label="Credential",
                    category="academic",
                    value="BTech",
                    normalized_value="BTech",
                    confidence=0.96,
                    page=1,
                    bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=40, y1=20),
                    requires_verification=True,
                )
            ],
        )
        plan = SessionVerificationPlan(
            session_id="provider-demo-academic",
            document_type="academic_credential",
            route_decisions=[
                VerifierRouteDecision(
                    credential_id="credential-1",
                    selected_verifier_key="academic_registry",
                    selected_verifier_label="Academic Registry",
                    route_reason="academic",
                    preferred_provider_key="entra_verified_id",
                    preferred_provider_label="Microsoft Entra Verified ID",
                    planned_provider_key="academic_registry_http",
                    planned_provider_label="Supplementary Academic Registry HTTP Provider",
                    planned_execution_mode="DEMO_PROVIDER",
                    planned_is_demo_result=True,
                    fallback_reason="SUPPLEMENTARY_PROVIDER_USED",
                )
            ],
            tasks=[
                VerificationTask(
                    task_id="task-academic-1",
                    credential_id="credential-1",
                    verifier_key="academic_registry",
                    verifier_label="Academic Registry",
                    verification_type="academic",
                    required=True,
                    status="PLANNED",
                    input_payload={
                        "label": "Credential",
                        "value": "BTech",
                        "preferred_provider_key": "entra_verified_id",
                        "preferred_provider_label": "Microsoft Entra Verified ID",
                        "planned_provider_key": "academic_registry_http",
                        "planned_provider_label": "Supplementary Academic Registry HTTP Provider",
                        "planned_execution_mode": "DEMO_PROVIDER",
                        "planned_is_demo_result": True,
                        "fallback_reason": "SUPPLEMENTARY_PROVIDER_USED",
                    },
                )
            ],
        )

        with patch.dict(
            os.environ,
            {
                "VERIFIER_PROVIDER_OPERATING_MODE": "DEMO_MOCK",
                "VERIFIER_DEMO_PROFILE_KEY": "certificate_partial_demo",
            },
            clear=False,
        ):
            artifacts = build_execution_artifacts(
                "provider-demo-academic",
                {"document_type": "academic_credential"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        self.assertEqual(result.raw_result_summary["provider_key"], "academic_registry_http")
        self.assertEqual(result.raw_result_summary["provider_operating_mode"], "DEMO_MOCK")
        self.assertTrue(result.raw_result_summary["provider_is_demo_result"])

    def test_local_mock_matches_aadhaar_value_from_local_verification_store(self):
        credentials, plan = self._build_local_store_inputs(
            session_id="provider-local-aadhaar",
            document_type="aadhaar_card",
            credential_id="aadhaar-number-1",
            label="Aadhaar Number",
            category="identity",
            value="9999 8888 7777",
            verifier_key="identity_db",
            verifier_label="Identity Database",
            verification_type="identity",
        )

        with patch(
            "backend.app.verifier_providers.providers.local_mock._load_local_verification_store",
            return_value={
                "records": [
                    {
                        "record_id": "aadhaar-record-1",
                        "document_types": ["aadhaar_card"],
                        "categories": ["identity"],
                        "verifier_keys": ["identity_db"],
                        "fields": [
                            {
                                "field_key": "aadhaar_number",
                                "label": "Aadhaar Number",
                                "label_aliases": ["aadhaar-number-1"],
                                "value": "9999 8888 7777",
                                "normalized_value": "999988887777",
                            }
                        ],
                    }
                ]
            },
        ):
            artifacts = build_execution_artifacts(
                "provider-local-aadhaar",
                {"document_type": "aadhaar_card"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.audit_status, "VERIFIED")
        self.assertEqual(result.raw_result_summary["provider_key"], "local_mock")
        self.assertEqual(result.matched_fields["aadhaar_number"], "9999 8888 7777")
        self.assertEqual(trace.provider_key, "local_mock")
        self.assertEqual(trace.response_summary["match_status"], "verified")

    def test_local_mock_execution_truth_is_explicit_when_entra_is_preferred(self):
        credentials, plan = self._build_identity_inputs(
            preferred_provider_key="entra_verified_id",
            planned_provider_key="local_mock",
            planned_execution_mode="LOCAL_MOCK",
            fallback_reason=FALLBACK_REASON_ENTRA_NOT_CONFIGURED,
        )

        artifacts = build_execution_artifacts(
            "provider-local-truth-session",
            {"document_type": "identity_document"},
            credentials=credentials,
            verification_plan=plan,
        )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.preferred_provider_key, "entra_verified_id")
        self.assertEqual(result.planned_provider_key, "local_mock")
        self.assertEqual(result.executed_provider_key, "local_mock")
        self.assertEqual(result.execution_mode, "LOCAL_MOCK")
        self.assertEqual(result.fallback_reason, FALLBACK_REASON_ENTRA_NOT_CONFIGURED)
        self.assertTrue(result.is_mock_result)
        self.assertFalse(result.is_live_result)
        self.assertFalse(result.is_demo_result)
        self.assertEqual(trace.provider_key, "local_mock")
        self.assertTrue(trace.is_mock_result)
        self.assertFalse(trace.is_live_result)

    def test_local_mock_reports_pan_mismatch_from_local_verification_store(self):
        credentials, plan = self._build_local_store_inputs(
            session_id="provider-local-pan",
            document_type="pan_card",
            credential_id="pan-number-1",
            label="PAN Number",
            category="tax",
            value="ZZZZZ9999Z",
            verifier_key="tax_authority",
            verifier_label="Tax Authority",
            verification_type="tax",
        )

        with patch(
            "backend.app.verifier_providers.providers.local_mock._load_local_verification_store",
            return_value={
                "records": [
                    {
                        "record_id": "pan-record-1",
                        "document_types": ["pan_card"],
                        "categories": ["tax"],
                        "verifier_keys": ["tax_authority"],
                        "fields": [
                            {
                                "field_key": "pan_number",
                                "label": "PAN Number",
                                "label_aliases": ["pan-number-1"],
                                "value": "ABCDE1234F",
                                "normalized_value": "ABCDE1234F",
                            }
                        ],
                    }
                ]
            },
        ):
            artifacts = build_execution_artifacts(
                "provider-local-pan",
                {"document_type": "pan_card"},
                credentials=credentials,
                verification_plan=plan,
            )

        result = artifacts["task_results"].results[0]
        trace = artifacts["provider_execution_traces"].traces[0]

        self.assertEqual(result.audit_status, "MISMATCH")
        self.assertEqual(result.raw_result_summary["provider_key"], "local_mock")
        self.assertEqual(
            result.mismatched_fields["pan_number"]["expected_value"],
            "ABCDE1234F",
        )
        self.assertEqual(trace.response_summary["match_status"], "mismatch")

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
        self.assertEqual(result.fallback_reason, FALLBACK_REASON_PROVIDER_ATTEMPT_FAILED)
        self.assertEqual(result.execution_mode, "RULE_ONLY_FALLBACK")
        self.assertEqual(trace.technical_status, "FAILED")
        self.assertTrue(trace.fallback_used)

    @staticmethod
    def _build_identity_inputs(
        preferred_provider_key=None,
        planned_provider_key=None,
        planned_execution_mode=None,
        fallback_reason=None,
    ):
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
                    preferred_provider_key=preferred_provider_key,
                    preferred_provider_label=(
                        "Microsoft Entra Verified ID"
                        if preferred_provider_key == "entra_verified_id"
                        else None
                    ),
                    planned_provider_key=planned_provider_key,
                    planned_provider_label=None,
                    planned_execution_mode=planned_execution_mode,
                    planned_is_live_result=planned_execution_mode == "LIVE_PROVIDER",
                    planned_is_mock_result=planned_provider_key == "local_mock",
                    planned_is_demo_result=planned_execution_mode == "DEMO_PROVIDER",
                    fallback_reason=fallback_reason,
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
                    input_payload={
                        "label": "Candidate Name",
                        "value": "Kanak Sharma",
                        "preferred_provider_key": preferred_provider_key,
                        "preferred_provider_label": (
                            "Microsoft Entra Verified ID"
                            if preferred_provider_key == "entra_verified_id"
                            else None
                        ),
                        "planned_provider_key": planned_provider_key,
                        "planned_provider_label": (
                            "Microsoft Entra Verified ID"
                            if planned_provider_key == "entra_verified_id"
                            else "Local Mock Provider"
                            if planned_provider_key == "local_mock"
                            else None
                        ),
                        "planned_execution_mode": planned_execution_mode,
                        "planned_is_live_result": planned_execution_mode == "LIVE_PROVIDER",
                        "planned_is_mock_result": planned_provider_key == "local_mock",
                        "planned_is_demo_result": planned_execution_mode == "DEMO_PROVIDER",
                        "fallback_reason": fallback_reason,
                    },
                )
            ],
        )
        return credentials, plan

    @staticmethod
    def _build_local_store_inputs(
        *,
        session_id,
        document_type,
        credential_id,
        label,
        category,
        value,
        verifier_key,
        verifier_label,
        verification_type,
    ):
        credentials = SessionCredentialCollection(
            session_id=session_id,
            document_type=document_type,
            credentials=[
                ExtractedCredential(
                    credential_id=credential_id,
                    label=label,
                    category=category,
                    value=value,
                    normalized_value=value,
                    confidence=0.98,
                    page=1,
                    bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=40, y1=20),
                    requires_verification=True,
                )
            ],
        )
        plan = SessionVerificationPlan(
            session_id=session_id,
            document_type=document_type,
            route_decisions=[
                VerifierRouteDecision(
                    credential_id=credential_id,
                    selected_verifier_key=verifier_key,
                    selected_verifier_label=verifier_label,
                    route_reason="fixture-backed local verification",
                    planned_provider_key="local_mock",
                    planned_provider_label="Local Mock Provider",
                    planned_execution_mode="LOCAL_MOCK",
                    planned_is_mock_result=True,
                )
            ],
            tasks=[
                VerificationTask(
                    task_id=f"task-{credential_id}",
                    credential_id=credential_id,
                    verifier_key=verifier_key,
                    verifier_label=verifier_label,
                    verification_type=verification_type,
                    required=True,
                    status="PLANNED",
                    input_payload={
                        "label": label,
                        "value": value,
                        "planned_provider_key": "local_mock",
                        "planned_provider_label": "Local Mock Provider",
                        "planned_execution_mode": "LOCAL_MOCK",
                        "planned_is_mock_result": True,
                    },
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
                "field_candidates": [
                    {
                        "candidate_id": "cand-name",
                        "label": "Candidate Name",
                        "category": "person_name",
                        "raw_value": "Kanak Sharma",
                        "normalized_value": "Kanak Sharma",
                        "source_text": "Candidate Name: Kanak Sharma",
                        "confidence": 0.98,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 40, "y1": 20},
                        "is_pii": True,
                        "requires_verification": True,
                        "verification_reason": "Identity claim",
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
        self.assertEqual(session.provider_operating_mode, "LIVE_DISABLED")
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
        mode_response = self.client.get("/session/provider-empty-session/provider-operating-mode")
        profile_response = self.client.get("/session/provider-empty-session/demo-profile")
        capabilities_response = self.client.get("/session/provider-empty-session/provider-capabilities")

        self.assertEqual(traces_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(mode_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(capabilities_response.status_code, 200)
        self.assertEqual(traces_response.json()["traces"], [])
        self.assertEqual(status_response.json()["provider_execution_status"], "NOT_STARTED")
        self.assertEqual(mode_response.json()["provider_operating_mode"], "LIVE_DISABLED")
        self.assertEqual(profile_response.json()["seeded"], False)
        self.assertTrue(any(cap["provider_key"] == "local_mock" for cap in capabilities_response.json()["capabilities"]))

    def test_demo_metadata_endpoints_report_seeded_demo_context_when_enabled(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="provider-demo-session",
            user_id="user-1",
            status=SessionState.VERIFYING,
            extraction_payload={"document_type": "academic_credential"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.close()

        with patch.dict(
            os.environ,
            {
                "VERIFIER_PROVIDER_OPERATING_MODE": "DEMO_MOCK",
                "VERIFIER_DEMO_PROFILE_KEY": "academic_transcript_demo",
            },
            clear=False,
        ):
            mode_response = self.client.get("/session/provider-demo-session/provider-operating-mode")
            profile_response = self.client.get("/session/provider-demo-session/demo-profile")

        self.assertEqual(mode_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(mode_response.json()["provider_operating_mode"], "DEMO_MOCK")
        self.assertEqual(mode_response.json()["demo_profile_key"], "academic_transcript_demo")
        self.assertEqual(profile_response.json()["profile_key"], "academic_transcript_demo")
        self.assertTrue(profile_response.json()["seeded"])

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
