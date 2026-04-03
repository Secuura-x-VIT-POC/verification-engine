import os
import sys
import unittest
from datetime import datetime

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
from backend.app.verification_domain.adapters import build_session_credential_audits
from backend.app.verification_domain.contracts import (
    BoundingBox,
    CredentialAuditCollection,
    ExtractedCredential,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    VerifierRouteDecision,
)
from backend.app.verifier_execution import (
    EXECUTION_STATUS_READY,
    TASK_STATUS_MANUAL_REVIEW,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_SUCCEEDED,
    CredentialVerificationBundle,
    CredentialVerificationBundleCollection,
    VerificationTaskResult,
    build_and_persist_execution_artifacts,
    build_execution_artifacts,
    build_default_verifier_registry,
)
from backend.app.verifier_execution.adapters import build_execution_context
from backend.app.verifier_execution.executor import VerificationTaskExecutor


def _sample_extraction_payload() -> dict:
    return {
        "document_type": "academic_credential",
        "page_count": 1,
        "used_ocr": False,
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
                "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 80, "y1": 20},
                "is_pii": True,
                "requires_verification": True,
                "verification_reason": "Identity claim",
            },
            {
                "candidate_id": "cand-institution",
                "label": "Institution",
                "category": "issuer",
                "raw_value": "VIT Vellore",
                "normalized_value": "VIT Vellore",
                "source_text": "Institution: VIT Vellore",
                "confidence": 0.97,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 25, "x1": 120, "y1": 35},
                "is_pii": False,
                "requires_verification": True,
                "verification_reason": "Issuer claim",
            },
            {
                "candidate_id": "cand-credential",
                "label": "Credential",
                "category": "credential_title",
                "raw_value": "BTech",
                "normalized_value": "BTech",
                "source_text": "Credential: BTech",
                "confidence": 0.96,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 40, "x1": 90, "y1": 50},
                "is_pii": False,
                "requires_verification": True,
                "verification_reason": "Academic credential",
            },
            {
                "candidate_id": "cand-id",
                "label": "Document ID",
                "category": "registration_number",
                "raw_value": "22BCE1234",
                "normalized_value": "22BCE1234",
                "source_text": "Document ID: 22BCE1234",
                "confidence": 0.95,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 55, "x1": 90, "y1": 65},
                "is_pii": False,
                "requires_verification": True,
                "verification_reason": "Academic identifier",
            },
        ],
    }


def _sample_connector_payload() -> list[dict]:
    return [
        {
            "connector_id": "vit_registry",
            "status": "VERIFIED",
            "reason_codes": ["REGISTRY_MATCH"],
            "matched_claims": {
                "name": "Kanak Sharma",
                "institution": "VIT Vellore",
                "degree": "BTech",
                "document_id": "22BCE1234",
            },
            "mismatched_claims": {},
            "assurance_class": "HIGH",
        }
    ]


class VerifierRegistryTests(unittest.TestCase):
    def test_default_registry_resolves_placeholder_verifiers(self):
        registry = build_default_verifier_registry()

        self.assertIsNotNone(registry.get("identity_db"))
        self.assertIsNotNone(registry.get("address_check"))
        self.assertIsNotNone(registry.get("passport_db"))
        self.assertIsNotNone(registry.get("academic_registry"))
        self.assertIsNotNone(registry.get("certificate_registry"))
        self.assertIsNotNone(registry.get("manual_review"))


class PlaceholderVerifierTests(unittest.TestCase):
    def test_placeholder_verifiers_return_structured_task_results(self):
        registry = build_default_verifier_registry()
        context = build_execution_context(
            session_id="session-1",
            document_type="mixed_document",
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome=None,
            reason_codes=[],
        )
        cases = [
            (
                "identity_db",
                ExtractedCredential(
                    credential_id="name-1",
                    label="Candidate Name",
                    category="identity",
                    value="Kanak Sharma",
                    normalized_value="Kanak Sharma",
                    confidence=0.98,
                    requires_verification=True,
                ),
            ),
            (
                "address_check",
                ExtractedCredential(
                    credential_id="address-1",
                    label="Address",
                    category="address",
                    value="42 Registry Road",
                    normalized_value="42 Registry Road",
                    confidence=0.93,
                    requires_verification=True,
                ),
            ),
            (
                "passport_db",
                ExtractedCredential(
                    credential_id="passport-1",
                    label="Passport Number",
                    category="passport",
                    value="P1234567",
                    normalized_value="P1234567",
                    confidence=0.91,
                    requires_verification=True,
                ),
            ),
            (
                "academic_registry",
                ExtractedCredential(
                    credential_id="degree-1",
                    label="Credential",
                    category="academic",
                    value="BTech",
                    normalized_value="BTech",
                    confidence=0.96,
                    requires_verification=True,
                ),
            ),
            (
                "certificate_registry",
                ExtractedCredential(
                    credential_id="certificate-1",
                    label="Certificate Number",
                    category="certificate",
                    value="CERT-42",
                    normalized_value="CERT-42",
                    confidence=0.88,
                    requires_verification=True,
                ),
            ),
            (
                "manual_review",
                ExtractedCredential(
                    credential_id="opaque-1",
                    label="Opaque Identifier",
                    category="unknown",
                    value="ZX-42",
                    normalized_value="ZX-42",
                    confidence=0.8,
                    requires_verification=True,
                ),
            ),
        ]

        for verifier_key, credential in cases:
            with self.subTest(verifier_key=verifier_key):
                task = VerificationTask(
                    task_id=f"task-{verifier_key}",
                    credential_id=credential.credential_id,
                    verifier_key=verifier_key,
                    verifier_label=verifier_key.replace("_", " ").title(),
                    verification_type=credential.category,
                    required=True,
                    status="PLANNED",
                    input_payload={"value": credential.normalized_value},
                )

                result = registry.get(verifier_key).execute(task, credential, context)

                self.assertEqual(result.task_id, task.task_id)
                self.assertEqual(result.credential_id, credential.credential_id)
                self.assertEqual(result.verifier_key, verifier_key)
                self.assertTrue(result.explanation)
                self.assertIn(result.task_status, {
                    TASK_STATUS_SUCCEEDED,
                    TASK_STATUS_PARTIAL,
                    TASK_STATUS_MANUAL_REVIEW,
                })


class VerificationExecutorTests(unittest.TestCase):
    def test_executor_handles_mixed_success_partial_and_manual_review(self):
        credentials = SessionCredentialCollection(
            session_id="session-exec",
            document_type="academic_credential",
            credentials=[
                ExtractedCredential(
                    credential_id="name-1",
                    label="Candidate Name",
                    category="identity",
                    value="Kanak Sharma",
                    normalized_value="Kanak Sharma",
                    confidence=0.98,
                    page=1,
                    requires_verification=True,
                ),
                ExtractedCredential(
                    credential_id="degree-1",
                    label="Credential",
                    category="academic",
                    value="BTech",
                    normalized_value="BTech",
                    confidence=0.96,
                    page=1,
                    requires_verification=True,
                ),
                ExtractedCredential(
                    credential_id="passport-1",
                    label="Passport Number",
                    category="passport",
                    value="P1234567",
                    normalized_value="P1234567",
                    confidence=0.91,
                    page=1,
                    bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=50, y1=20),
                    requires_verification=True,
                ),
                ExtractedCredential(
                    credential_id="opaque-1",
                    label="Opaque Identifier",
                    category="unknown",
                    value="ZX-42",
                    normalized_value="ZX-42",
                    confidence=0.8,
                    page=1,
                    requires_verification=True,
                ),
            ],
        )
        plan = SessionVerificationPlan(
            session_id="session-exec",
            document_type="academic_credential",
            route_decisions=[
                VerifierRouteDecision(
                    credential_id="name-1",
                    selected_verifier_key="identity_db",
                    selected_verifier_label="Identity Database",
                    route_reason="identity",
                ),
                VerifierRouteDecision(
                    credential_id="degree-1",
                    selected_verifier_key="academic_registry",
                    selected_verifier_label="Academic Registry",
                    route_reason="academic",
                ),
                VerifierRouteDecision(
                    credential_id="passport-1",
                    selected_verifier_key="passport_db",
                    selected_verifier_label="Passport Database",
                    route_reason="passport",
                ),
                VerifierRouteDecision(
                    credential_id="opaque-1",
                    selected_verifier_key="manual_review",
                    selected_verifier_label="Manual Review",
                    route_reason="unknown",
                    manual_review_recommended=True,
                ),
            ],
            tasks=[
                VerificationTask(
                    task_id="task-name",
                    credential_id="name-1",
                    verifier_key="identity_db",
                    verifier_label="Identity Database",
                    verification_type="identity",
                    required=True,
                    status="PLANNED",
                ),
                VerificationTask(
                    task_id="task-degree",
                    credential_id="degree-1",
                    verifier_key="academic_registry",
                    verifier_label="Academic Registry",
                    verification_type="academic",
                    required=True,
                    status="PLANNED",
                ),
                VerificationTask(
                    task_id="task-passport",
                    credential_id="passport-1",
                    verifier_key="passport_db",
                    verifier_label="Passport Database",
                    verification_type="passport",
                    required=True,
                    status="PLANNED",
                ),
                VerificationTask(
                    task_id="task-opaque",
                    credential_id="opaque-1",
                    verifier_key="manual_review",
                    verifier_label="Manual Review",
                    verification_type="unknown",
                    required=True,
                    status="PLANNED",
                ),
            ],
        )
        context = build_execution_context(
            session_id="session-exec",
            document_type="academic_credential",
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome=None,
            reason_codes=[],
        )

        executor = VerificationTaskExecutor()
        artifacts = executor.execute_plan(
            credential_collection=credentials,
            verification_plan=plan,
            context=context,
        )

        summary = artifacts["execution_summary"]
        bundles = artifacts["credential_bundles"]

        self.assertEqual(summary.total_tasks, 4)
        self.assertEqual(summary.succeeded_tasks, 2)
        self.assertEqual(summary.partial_tasks, 1)
        self.assertEqual(summary.manual_review_tasks, 1)
        self.assertEqual(summary.overall_execution_status, EXECUTION_STATUS_READY)
        bundle_map = {bundle.credential_id: bundle for bundle in bundles.bundles}
        self.assertEqual(bundle_map["name-1"].final_audit_status, "VERIFIED")
        self.assertEqual(bundle_map["degree-1"].final_audit_status, "VERIFIED")
        self.assertEqual(bundle_map["passport-1"].final_audit_status, "PARTIAL")
        self.assertEqual(bundle_map["opaque-1"].final_audit_status, "MANUAL_REVIEW")


class VerificationExecutionServiceTests(unittest.TestCase):
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

    def test_execution_artifacts_persist_on_session_row(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-persisted-execution",
            user_id="user-1",
            status=SessionState.VERIFYING,
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        artifacts = build_and_persist_execution_artifacts(session)
        db.commit()
        db.refresh(session)

        self.assertEqual(session.verification_execution_status, EXECUTION_STATUS_READY)
        self.assertIsNotNone(session.verification_task_results_payload)
        self.assertIsNotNone(session.credential_verification_bundles_payload)
        self.assertIsNotNone(session.verification_execution_summary_payload)
        self.assertIsNotNone(session.provider_execution_traces_payload)
        self.assertEqual(session.provider_execution_status, "NOT_STARTED")
        self.assertEqual(artifacts["execution_summary"].succeeded_tasks, 4)
        db.close()

    def test_audit_assembly_prefers_task_results_over_legacy_connector_fallback(self):
        credential = ExtractedCredential(
            credential_id="name-1",
            label="Candidate Name",
            category="identity",
            value="Kanak Sharma",
            normalized_value="Kanak Sharma",
            confidence=0.98,
            requires_verification=True,
        )
        bundle = CredentialVerificationBundle(
            credential_id="name-1",
            label="Candidate Name",
            category="identity",
            selected_task_ids=["task-name"],
            result_count=1,
            final_audit_status="PARTIAL",
            final_outcome_color="amber",
            explanation="Task-driven audit says partial evidence only.",
            reason_codes=["TASK_DRIVEN_PARTIAL"],
            best_result=VerificationTaskResult(
                task_id="task-name",
                credential_id="name-1",
                verifier_key="identity_db",
                verifier_label="Identity Database",
                task_status="PARTIAL",
                audit_status="PARTIAL",
                outcome_color="amber",
                explanation="Task-driven audit says partial evidence only.",
                reason_codes=["TASK_DRIVEN_PARTIAL"],
            ),
            all_results=[],
        )

        audits = build_session_credential_audits(
            "session-audits",
            _sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            credentials=SessionCredentialCollection(
                session_id="session-audits",
                document_type="academic_credential",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-audits",
                document_type="academic_credential",
                route_decisions=[
                    VerifierRouteDecision(
                        credential_id="name-1",
                        selected_verifier_key="identity_db",
                        selected_verifier_label="Identity Database",
                        route_reason="identity",
                    )
                ],
                tasks=[],
            ),
            credential_bundles=CredentialVerificationBundleCollection(
                session_id="session-audits",
                document_type="academic_credential",
                bundles=[bundle],
            ),
        )

        self.assertEqual(audits.audits[0].audit_status, "PARTIAL")
        self.assertEqual(audits.audits[0].reason_codes, ["TASK_DRIVEN_PARTIAL"])
        self.assertEqual(audits.audits[0].explanation, "Task-driven audit says partial evidence only.")


class VerificationExecutionApiTests(unittest.TestCase):
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

    def test_execution_endpoints_return_safe_empty_payloads(self):
        self._create_session("session-empty-execution", SessionState.CREATED)

        results_response = self.client.get("/session/session-empty-execution/verification-task-results")
        bundles_response = self.client.get("/session/session-empty-execution/credential-bundles")
        status_response = self.client.get("/session/session-empty-execution/verification-execution-status")

        self.assertEqual(results_response.status_code, 200)
        self.assertEqual(bundles_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(
            results_response.json(),
            {
                "session_id": "session-empty-execution",
                "document_type": "unknown",
                "results": [],
            },
        )
        self.assertEqual(
            bundles_response.json(),
            {
                "session_id": "session-empty-execution",
                "document_type": "unknown",
                "bundles": [],
            },
        )
        self.assertEqual(status_response.json()["verification_execution_status"], "NOT_STARTED")

    def test_execution_endpoints_compute_for_legacy_rows_when_payloads_are_missing(self):
        self._create_session(
            "session-legacy-execution",
            SessionState.VERIFIED_GREEN,
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
        )

        results_response = self.client.get("/session/session-legacy-execution/verification-task-results")
        bundles_response = self.client.get("/session/session-legacy-execution/credential-bundles")
        status_response = self.client.get("/session/session-legacy-execution/verification-execution-status")

        self.assertEqual(results_response.status_code, 200)
        self.assertEqual(bundles_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(len(results_response.json()["results"]), 4)
        self.assertEqual(len(bundles_response.json()["bundles"]), 4)
        self.assertEqual(status_response.json()["verification_execution_status"], "READY")
        self.assertTrue(status_response.json()["task_results_available"])

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _create_session(
        self,
        session_id: str,
        status: str,
        *,
        extraction_payload: dict | None = None,
        connector_payload: list[dict] | None = None,
        trust_outcome: str | None = None,
        reason_codes: list[str] | None = None,
    ) -> None:
        db = self.SessionLocal()
        session = SessionModel(
            id=session_id,
            user_id="user-1",
            status=status,
            extraction_payload=extraction_payload,
            connector_payload=connector_payload,
            trust_outcome=trust_outcome,
            reason_codes=reason_codes or [],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.close()


if __name__ == "__main__":
    unittest.main()
