import os
import sys
import unittest
import json
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
from backend.app.sessions.models import Session as SessionModel
from backend.app.verification_domain.adapters import build_session_credential_audits
from backend.app.verification_domain.adapters import build_session_verification_plan
from backend.app.verification_domain.contracts import (
    BoundingBox,
    CredentialAuditCollection,
    FALLBACK_REASON_ENTRA_NOT_CONFIGURED,
    FALLBACK_REASON_MANUAL_REVIEW_ONLY,
    ExtractedCredential,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    VerifierRouteDecision,
)
from backend.app.verifier_execution import (
    EXECUTION_STATUS_READY,
    TASK_STATUS_FAILED,
    TASK_STATUS_MANUAL_REVIEW,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_SUCCEEDED,
    CredentialVerificationBundle,
    CredentialVerificationBundleCollection,
    VerificationTaskResult,
    build_execution_artifacts,
    build_default_verifier_registry,
)
from backend.app.verifier_execution.adapters import build_execution_context
from backend.app.verifier_execution.executor import VerificationTaskExecutor


class _FakeProviderRegistry:
    def __init__(self, providers: dict[str, object] | None = None):
        self.providers = dict(providers or {})

    def get(self, provider_key: str):
        return self.providers.get(provider_key)


class _FakeProviderRuntime:
    def __init__(self, providers: dict[str, object] | None = None):
        self.registry = _FakeProviderRegistry(providers)


class _CapabilityMismatchProvider:
    provider_key = "wrong_category_provider"
    provider_label = "Wrong Category Provider"

    def supports(self, verifier_key: str, category: str) -> bool:
        return False


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
    def _single_identity_credential_collection(
        self,
        *,
        credential_id: str = "name-1",
    ) -> SessionCredentialCollection:
        return SessionCredentialCollection(
            session_id="session-exec-safety",
            document_type="identity_document",
            credentials=[
                ExtractedCredential(
                    credential_id=credential_id,
                    label="Candidate Name",
                    category="identity",
                    value="Kanak Sharma",
                    normalized_value="Kanak Sharma",
                    confidence=0.98,
                    requires_verification=True,
                )
            ],
        )

    def _single_task_plan(
        self,
        *,
        credential_id: str = "name-1",
        verifier_key: str = "identity_db",
        verifier_label: str = "Identity Database",
        provider_candidates: list[str] | None = None,
    ) -> SessionVerificationPlan:
        return SessionVerificationPlan(
            session_id="session-exec-safety",
            document_type="identity_document",
            route_decisions=[
                VerifierRouteDecision(
                    credential_id=credential_id,
                    selected_verifier_key=verifier_key,
                    selected_verifier_label=verifier_label,
                    route_reason="safety test route",
                )
            ],
            tasks=[
                VerificationTask(
                    task_id="task-name",
                    credential_id=credential_id,
                    verifier_key=verifier_key,
                    verifier_label=verifier_label,
                    verification_type="identity",
                    required=True,
                    status="PLANNED",
                    provider_candidates=list(provider_candidates or []),
                    input_payload={
                        "label": "Candidate Name",
                        "value": "Kanak Sharma",
                        "preferred_provider_key": (
                            provider_candidates[0] if provider_candidates else None
                        ),
                    },
                )
            ],
        )

    def _empty_context(self, *, provider_runtime=None):
        return build_execution_context(
            session_id="session-exec-safety",
            document_type="identity_document",
            extraction_payload={"document_type": "identity_document"},
            connector_payload=[],
            trust_outcome=None,
            reason_codes=[],
            provider_runtime=provider_runtime,
        )

    def test_unknown_provider_candidate_is_skipped_and_falls_back_to_manual_review(self):
        artifacts = VerificationTaskExecutor().execute_plan(
            credential_collection=self._single_identity_credential_collection(),
            verification_plan=self._single_task_plan(provider_candidates=["unknown_provider"]),
            context=self._empty_context(),
        )

        result = artifacts["task_results"].results[0]

        self.assertEqual(result.task_status, TASK_STATUS_MANUAL_REVIEW)
        self.assertEqual(result.audit_status, "MANUAL_REVIEW")
        self.assertEqual(result.outcome_color, "amber")
        self.assertTrue(result.manual_review_recommended)
        self.assertIn("PROVIDER_NOT_REGISTERED", result.reason_codes)
        self.assertIn("NO_PROVIDER_AVAILABLE", result.reason_codes)
        self.assertEqual(result.fallback_reason, "NO_EXECUTABLE_PROVIDER")
        self.assertNotEqual(result.audit_status, "VERIFIED")
        self.assertNotEqual(result.outcome_color, "green")

    def test_provider_capability_mismatch_is_skipped_and_falls_back_to_manual_review(self):
        runtime = _FakeProviderRuntime(
            {"wrong_category_provider": _CapabilityMismatchProvider()}
        )

        artifacts = VerificationTaskExecutor().execute_plan(
            credential_collection=self._single_identity_credential_collection(),
            verification_plan=self._single_task_plan(
                provider_candidates=["wrong_category_provider"]
            ),
            context=self._empty_context(provider_runtime=runtime),
        )

        result = artifacts["task_results"].results[0]

        self.assertEqual(result.task_status, TASK_STATUS_MANUAL_REVIEW)
        self.assertEqual(result.audit_status, "MANUAL_REVIEW")
        self.assertEqual(result.outcome_color, "amber")
        self.assertIn("PROVIDER_CAPABILITY_MISMATCH", result.reason_codes)
        self.assertIn("NO_PROVIDER_AVAILABLE", result.reason_codes)
        self.assertTrue(result.manual_review_recommended)
        self.assertNotEqual(result.audit_status, "VERIFIED")
        self.assertNotEqual(result.outcome_color, "green")

    def test_no_executable_provider_available_becomes_manual_review_result(self):
        artifacts = VerificationTaskExecutor().execute_plan(
            credential_collection=self._single_identity_credential_collection(),
            verification_plan=self._single_task_plan(
                verifier_key="unregistered_verifier",
                verifier_label="Unregistered Verifier",
                provider_candidates=["unregistered_provider"],
            ),
            context=self._empty_context(),
        )

        result = artifacts["task_results"].results[0]

        self.assertEqual(result.task_status, TASK_STATUS_MANUAL_REVIEW)
        self.assertEqual(result.audit_status, "MANUAL_REVIEW")
        self.assertEqual(result.outcome_color, "amber")
        self.assertEqual(result.fallback_reason, "NO_EXECUTABLE_PROVIDER")
        self.assertIn("VERIFIER_NOT_REGISTERED", result.reason_codes)
        self.assertIn("NO_PROVIDER_AVAILABLE", result.reason_codes)
        self.assertLess(result.confidence or 0.0, 0.99)
        self.assertNotEqual(result.audit_status, "VERIFIED")
        self.assertNotEqual(result.outcome_color, "green")

    def test_missing_credential_reference_is_handled_without_false_verification(self):
        artifacts = VerificationTaskExecutor().execute_plan(
            credential_collection=self._single_identity_credential_collection(
                credential_id="name-1"
            ),
            verification_plan=self._single_task_plan(credential_id="missing-name"),
            context=self._empty_context(),
        )

        result = artifacts["task_results"].results[0]

        self.assertEqual(result.task_status, TASK_STATUS_FAILED)
        self.assertEqual(result.audit_status, "MANUAL_REVIEW")
        self.assertEqual(result.outcome_color, "amber")
        self.assertTrue(result.manual_review_recommended)
        self.assertIn("MISSING_CREDENTIAL_REFERENCE", result.reason_codes)
        self.assertEqual(result.execution_mode, "EXECUTOR_FAILURE")
        self.assertNotEqual(result.audit_status, "VERIFIED")
        self.assertNotEqual(result.outcome_color, "green")

    def test_provider_mismatch_result_remains_red_through_bundle_selection(self):
        credentials = self._single_identity_credential_collection()
        plan = self._single_task_plan()
        mismatch = VerificationTaskResult(
            task_id="task-mismatch",
            credential_id="name-1",
            verifier_key="identity_db",
            verifier_label="Identity Database",
            executed_provider_key="local_mock",
            executed_provider_label="Local Mock Provider",
            task_status="SUCCEEDED",
            audit_status="MISMATCH",
            outcome_color="red",
            explanation="Provider returned contradictory evidence.",
            reason_codes=["PROVIDER_MISMATCH"],
            mismatched_fields={"name": {"document_value": "Kanak", "expected_value": "Asha"}},
            confidence=0.98,
        )
        manual_review = VerificationTaskResult(
            task_id="task-review",
            credential_id="name-1",
            verifier_key="manual_review",
            verifier_label="Manual Review",
            task_status="MANUAL_REVIEW",
            audit_status="MANUAL_REVIEW",
            outcome_color="amber",
            explanation="Manual review fallback.",
            reason_codes=["MANUAL_REVIEW_REQUIRED"],
            confidence=0.0,
            manual_review_recommended=True,
        )
        verified = VerificationTaskResult(
            task_id="task-verified",
            credential_id="name-1",
            verifier_key="identity_db",
            verifier_label="Identity Database",
            task_status="SUCCEEDED",
            audit_status="VERIFIED",
            outcome_color="green",
            explanation="A later result claims a match.",
            reason_codes=["PROVIDER_VERIFIED"],
            confidence=0.99,
        )

        bundles = VerificationTaskExecutor()._build_bundles(
            credential_collection=credentials,
            verification_plan=plan,
            results=[manual_review, verified, mismatch],
        )

        bundle = bundles.bundles[0]
        self.assertEqual(bundle.best_result.task_id, "task-mismatch")
        self.assertEqual(bundle.final_audit_status, "MISMATCH")
        self.assertEqual(bundle.final_outcome_color, "red")
        self.assertIn("PROVIDER_MISMATCH", bundle.reason_codes)
        self.assertNotEqual(bundle.final_audit_status, "VERIFIED")
        self.assertNotEqual(bundle.final_outcome_color, "green")

    def test_audit_assembly_does_not_expose_raw_credential_values(self):
        credentials = SessionCredentialCollection(
            session_id="session-privacy-audit",
            document_type="identity_document",
            credentials=[
                ExtractedCredential(
                    credential_id="credential-name",
                    label="Candidate Name",
                    category="identity",
                    value="RAW_PERSON_NAME_SECRET_123",
                    normalized_value="RAW_ID_NUMBER_SECRET_123",
                    source_text="RAW_SOURCE_TEXT_SECRET_123",
                    page=1,
                    bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=80, y1=20),
                    confidence=0.98,
                    requires_verification=True,
                    extraction_method="unit_test",
                )
            ],
        )
        plan = SessionVerificationPlan(
            session_id="session-privacy-audit",
            document_type="identity_document",
            route_decisions=[
                VerifierRouteDecision(
                    credential_id="credential-name",
                    selected_verifier_key="manual_review",
                    selected_verifier_label="Manual Review",
                    route_reason="manual review",
                    manual_review_recommended=True,
                )
            ],
            tasks=[],
        )

        audits = build_session_credential_audits(
            "session-privacy-audit",
            {"document_type": "identity_document"},
            credentials=credentials,
            verification_plan=plan,
        )
        serialized = json.dumps(audits.model_dump(mode="json"), sort_keys=True)

        self.assertNotIn("RAW_PERSON_NAME_SECRET_123", serialized)
        self.assertNotIn("RAW_ID_NUMBER_SECRET_123", serialized)
        self.assertNotIn("RAW_SOURCE_TEXT_SECRET_123", serialized)
        audit = audits.audits[0]
        self.assertIsNone(audit.document_value)
        self.assertIsNone(audit.normalized_value)

    def test_extraction_evidence_keeps_safe_metadata_only(self):
        credential = ExtractedCredential(
            credential_id="credential-name",
            label="Candidate Name",
            category="identity",
            value="RAW_PERSON_NAME_SECRET_123",
            normalized_value="RAW_ID_NUMBER_SECRET_123",
            source_text="RAW_SOURCE_TEXT_SECRET_123",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=80, y1=20),
            confidence=0.98,
            requires_verification=True,
            extraction_method="unit_test",
        )
        audits = build_session_credential_audits(
            "session-safe-evidence",
            {"document_type": "identity_document"},
            credentials=SessionCredentialCollection(
                session_id="session-safe-evidence",
                document_type="identity_document",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-safe-evidence",
                document_type="identity_document",
                route_decisions=[
                    VerifierRouteDecision(
                        credential_id="credential-name",
                        selected_verifier_key="manual_review",
                        selected_verifier_label="Manual Review",
                        route_reason="manual review",
                        manual_review_recommended=True,
                    )
                ],
                tasks=[],
            ),
        )

        extraction_item = next(
            item for item in audits.audits[0].evidence if item.evidence_type == "document_extraction"
        )

        self.assertEqual(
            set(extraction_item.detail.keys()),
            {
                "credential_id",
                "label",
                "category",
                "field_local_only",
                "page",
                "bounding_box",
                "confidence",
                "extraction_method",
            },
        )
        self.assertEqual(extraction_item.detail["credential_id"], "credential-name")
        self.assertEqual(extraction_item.detail["label"], "Candidate Name")
        self.assertEqual(extraction_item.detail["category"], "identity")
        self.assertEqual(extraction_item.detail["bounding_box"]["x0"], 10)
        serialized = json.dumps(extraction_item.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn("source_text", serialized)
        self.assertNotIn("normalized_value", serialized)
        self.assertNotIn("RAW_SOURCE_TEXT_SECRET_123", serialized)
        self.assertNotIn("RAW_ID_NUMBER_SECRET_123", serialized)

    def test_task_result_evidence_does_not_include_raw_provider_summary(self):
        credential = ExtractedCredential(
            credential_id="credential-name",
            label="Candidate Name",
            category="identity",
            value="RAW_PERSON_NAME_SECRET_123",
            normalized_value="RAW_ID_NUMBER_SECRET_123",
            source_text="RAW_SOURCE_TEXT_SECRET_123",
            confidence=0.98,
            requires_verification=True,
        )
        result = VerificationTaskResult(
            task_id="task-name",
            credential_id="credential-name",
            verifier_key="identity_db",
            verifier_label="Identity Database",
            executed_provider_key="local_mock",
            executed_provider_label="Local Mock Provider",
            execution_mode="LOCAL_MOCK",
            task_status="SUCCEEDED",
            audit_status="MISMATCH",
            outcome_color="red",
            explanation="Provider returned contradictory evidence.",
            reason_codes=["PROVIDER_MISMATCH"],
            matched_fields={"name": "RAW_PERSON_NAME_SECRET_123"},
            mismatched_fields={
                "document_id": {
                    "document_value": "RAW_ID_NUMBER_SECRET_123",
                    "expected_value": "RAW_PROVIDER_SECRET_123",
                }
            },
            missing_fields=["Candidate Name"],
            raw_result_summary={
                "provider_key": "local_mock",
                "provider_label": "Local Mock Provider",
                "provider_response_summary": {
                    "raw_provider_body": "RAW_PROVIDER_SECRET_123",
                    "safe_mode": "local_mock",
                },
                "raw_result_summary": "RAW_PROVIDER_SECRET_123",
                "execution_mode": "LOCAL_MOCK",
            },
            confidence=0.98,
        )
        bundle = CredentialVerificationBundle(
            credential_id="credential-name",
            label="Candidate Name",
            category="identity",
            selected_task_ids=["task-name"],
            result_count=1,
            final_audit_status="MISMATCH",
            final_outcome_color="red",
            explanation="Provider returned contradictory evidence.",
            reason_codes=["PROVIDER_MISMATCH"],
            best_result=result,
            all_results=[],
        )
        audits = build_session_credential_audits(
            "session-provider-privacy",
            {"document_type": "identity_document"},
            credentials=SessionCredentialCollection(
                session_id="session-provider-privacy",
                document_type="identity_document",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-provider-privacy",
                document_type="identity_document",
                route_decisions=[
                    VerifierRouteDecision(
                        credential_id="credential-name",
                        selected_verifier_key="identity_db",
                        selected_verifier_label="Identity Database",
                        route_reason="identity",
                    )
                ],
                tasks=[],
            ),
            credential_bundles=CredentialVerificationBundleCollection(
                session_id="session-provider-privacy",
                document_type="identity_document",
                bundles=[bundle],
            ),
        )
        serialized = json.dumps(audits.model_dump(mode="json"), sort_keys=True)

        self.assertNotIn("RAW_PROVIDER_SECRET_123", serialized)
        self.assertNotIn("RAW_PERSON_NAME_SECRET_123", serialized)
        self.assertNotIn("RAW_ID_NUMBER_SECRET_123", serialized)
        self.assertNotIn("raw_result_summary", serialized)
        audit = audits.audits[0]
        self.assertEqual(audit.audit_status, "MISMATCH")
        self.assertEqual(audit.outcome_color, "red")
        self.assertEqual(audit.reason_codes, ["PROVIDER_MISMATCH"])
        self.assertEqual(audit.matched_fields, {"name": True})
        self.assertEqual(audit.mismatched_fields, {"document_id": True})
        task_item = next(
            item for item in audit.evidence if item.evidence_type == "verification_task_result"
        )
        self.assertEqual(task_item.detail["matched_fields"], {"name": True})
        self.assertEqual(task_item.detail["mismatched_fields"], {"document_id": True})

    def test_route_plan_marks_entra_preferred_but_local_mock_planned_honestly(self):
        credentials = SessionCredentialCollection(
            session_id="session-route-truth",
            document_type="identity_document",
            credentials=[
                ExtractedCredential(
                    credential_id="name-1",
                    label="Candidate Name",
                    category="identity",
                    value="Kanak Sharma",
                    normalized_value="Kanak Sharma",
                    confidence=0.98,
                    requires_verification=True,
                )
            ],
        )

        plan = build_session_verification_plan(
            "session-route-truth",
            {"document_type": "identity_document"},
            credentials=credentials,
        )

        decision = plan.route_decisions[0]
        task = plan.tasks[0]

        self.assertEqual(decision.preferred_provider_key, "entra_verified_id")
        self.assertEqual(decision.planned_provider_key, "local_mock")
        self.assertEqual(decision.planned_execution_mode, "LOCAL_MOCK")
        self.assertEqual(decision.fallback_reason, FALLBACK_REASON_ENTRA_NOT_CONFIGURED)
        self.assertTrue(decision.planned_is_mock_result)
        self.assertEqual(task.input_payload["planned_provider_key"], "local_mock")
        self.assertEqual(task.input_payload["planned_execution_mode"], "LOCAL_MOCK")
        self.assertEqual(task.input_payload["fallback_reason"], FALLBACK_REASON_ENTRA_NOT_CONFIGURED)

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

    def test_execution_artifacts_are_built_without_session_persistence(self):
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

        artifacts = build_execution_artifacts(
            session.id,
            session.extraction_payload,
            connector_payload=session.connector_payload,
        )
        db.commit()
        db.refresh(session)

        self.assertIsNone(session.verification_task_results_payload)
        self.assertIsNone(session.credential_verification_bundles_payload)
        self.assertIsNone(session.verification_execution_summary_payload)
        self.assertIsNone(session.provider_execution_traces_payload)
        self.assertEqual(session.provider_execution_status, "NOT_STARTED")
        self.assertEqual(artifacts["execution_summary"].succeeded_tasks, 3)
        db.close()

    def test_manual_only_mode_keeps_route_truth_honest(self):
        credentials = SessionCredentialCollection(
            session_id="session-manual-mode",
            document_type="identity_document",
            credentials=[
                ExtractedCredential(
                    credential_id="name-1",
                    label="Candidate Name",
                    category="identity",
                    value="Kanak Sharma",
                    normalized_value="Kanak Sharma",
                    confidence=0.98,
                    requires_verification=True,
                )
            ],
        )

        with patch.dict(
            os.environ,
            {
                "VERIFIER_PROVIDER_OPERATING_MODE": "MANUAL_ONLY",
            },
            clear=False,
        ):
            plan = build_session_verification_plan(
                "session-manual-mode",
                {"document_type": "identity_document"},
                credentials=credentials,
            )

        decision = plan.route_decisions[0]
        self.assertEqual(decision.selected_verifier_key, "manual_review")
        self.assertEqual(decision.fallback_reason, FALLBACK_REASON_MANUAL_REVIEW_ONLY)
        self.assertEqual(decision.planned_execution_mode, "MANUAL_REVIEW")

    def test_audit_assembly_prefers_task_results_over_legacy_connector_fallback(self):
        credential = ExtractedCredential(
            credential_id="name-1",
            label="Candidate Name",
            category="identity",
            value="Kanak Sharma",
            normalized_value="Kanak Sharma",
            source_text="Candidate Name: Kanak Sharma",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=80, y1=20),
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
        self.assertEqual(
            [item.evidence_type for item in audits.audits[0].evidence],
            ["verification_task_result", "document_extraction", "route_metadata"],
        )
        self.assertFalse(any(item.evidence_type == "trust_result" for item in audits.audits[0].evidence))
        self.assertFalse(any(item.evidence_type == "connector_response" for item in audits.audits[0].evidence))

    def test_unrelated_connector_and_trust_data_do_not_contaminate_other_audit_cards(self):
        name_credential = ExtractedCredential(
            credential_id="name-1",
            label="Candidate Name",
            category="identity",
            value="Kanak Sharma",
            normalized_value="Kanak Sharma",
            source_text="Candidate Name: Kanak Sharma",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=80, y1=20),
            confidence=0.98,
            requires_verification=True,
        )
        address_credential = ExtractedCredential(
            credential_id="address-1",
            label="Home Address",
            category="address",
            value="42 Registry Road",
            normalized_value="42 Registry Road",
            source_text="Home Address: 42 Registry Road",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=40, x1=135, y1=50),
            confidence=0.92,
            requires_verification=True,
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
                credentials=[name_credential, address_credential],
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
                    ),
                    VerifierRouteDecision(
                        credential_id="address-1",
                        selected_verifier_key="address_check",
                        selected_verifier_label="Address Check",
                        route_reason="address",
                    ),
                ],
                tasks=[],
            ),
        )

        audits_by_id = {audit.credential_id: audit for audit in audits.audits}
        name_audit = audits_by_id["name-1"]
        address_audit = audits_by_id["address-1"]

        self.assertEqual(name_audit.audit_status, "VERIFIED")
        self.assertEqual(address_audit.audit_status, "PARTIAL")
        self.assertEqual(name_audit.matched_fields, {"name": True})
        self.assertEqual(address_audit.matched_fields, {})
        self.assertTrue(any(item.evidence_type == "connector_claim_summary" for item in name_audit.evidence))
        self.assertFalse(any(item.evidence_type == "connector_claim_summary" for item in address_audit.evidence))
        self.assertFalse(any(item.evidence_type == "trust_result" for item in address_audit.evidence))
        self.assertEqual(
            [item.evidence_type for item in address_audit.evidence],
            ["document_extraction", "route_metadata"],
        )

        extraction_item = next(item for item in address_audit.evidence if item.evidence_type == "document_extraction")
        self.assertEqual(extraction_item.detail["bounding_box"]["x0"], 10)
        self.assertNotIn("source_text", extraction_item.detail)
        self.assertNotIn("normalized_value", extraction_item.detail)

    def test_audit_provider_evidence_distinguishes_preference_plan_and_execution(self):
        credential = ExtractedCredential(
            credential_id="name-1",
            label="Candidate Name",
            category="identity",
            value="Kanak Sharma",
            normalized_value="Kanak Sharma",
            source_text="Candidate Name: Kanak Sharma",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=80, y1=20),
            confidence=0.98,
            requires_verification=True,
        )
        bundle = CredentialVerificationBundle(
            credential_id="name-1",
            label="Candidate Name",
            category="identity",
            selected_task_ids=["task-name"],
            result_count=1,
            final_audit_status="VERIFIED",
            final_outcome_color="green",
            explanation="Identity Database matched bounded local mock evidence via Local Mock Provider.",
            reason_codes=["PROVIDER_VERIFIED", FALLBACK_REASON_ENTRA_NOT_CONFIGURED],
            best_result=VerificationTaskResult(
                task_id="task-name",
                credential_id="name-1",
                verifier_key="identity_db",
                verifier_label="Identity Database",
                preferred_provider_key="entra_verified_id",
                preferred_provider_label="Microsoft Entra Verified ID",
                planned_provider_key="local_mock",
                planned_provider_label="Local Mock Provider",
                executed_provider_key="local_mock",
                executed_provider_label="Local Mock Provider",
                execution_mode="LOCAL_MOCK",
                fallback_reason=FALLBACK_REASON_ENTRA_NOT_CONFIGURED,
                is_mock_result=True,
                task_status="SUCCEEDED",
                audit_status="VERIFIED",
                outcome_color="green",
                explanation="Identity Database matched bounded local mock evidence via Local Mock Provider.",
                reason_codes=["PROVIDER_VERIFIED", FALLBACK_REASON_ENTRA_NOT_CONFIGURED],
                raw_result_summary={
                    "provider_key": "local_mock",
                    "provider_label": "Local Mock Provider",
                    "provider_response_summary": {"mode": "local_verification_store"},
                    "provider_is_mock_result": True,
                    "provider_is_demo_result": False,
                    "provider_is_live_result": False,
                },
            ),
            all_results=[],
        )

        audits = build_session_credential_audits(
            "session-audits",
            {"document_type": "identity_document"},
            credentials=SessionCredentialCollection(
                session_id="session-audits",
                document_type="identity_document",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-audits",
                document_type="identity_document",
                route_decisions=[
                    VerifierRouteDecision(
                        credential_id="name-1",
                        selected_verifier_key="identity_db",
                        selected_verifier_label="Identity Database",
                        route_reason="Identity credential. Microsoft Entra Verified ID is preferred, but local mock is planned in this environment.",
                        preferred_provider_key="entra_verified_id",
                        preferred_provider_label="Microsoft Entra Verified ID",
                        planned_provider_key="local_mock",
                        planned_provider_label="Local Mock Provider",
                        planned_execution_mode="LOCAL_MOCK",
                        planned_is_mock_result=True,
                        fallback_reason=FALLBACK_REASON_ENTRA_NOT_CONFIGURED,
                    )
                ],
                tasks=[],
            ),
            credential_bundles=CredentialVerificationBundleCollection(
                session_id="session-audits",
                document_type="identity_document",
                bundles=[bundle],
            ),
        )

        provider_item = next(
            item for item in audits.audits[0].evidence if item.evidence_type == "provider_response_summary"
        )

        self.assertEqual(provider_item.detail["preferred_provider_key"], "entra_verified_id")
        self.assertEqual(provider_item.detail["planned_provider_key"], "local_mock")
        self.assertEqual(provider_item.detail["executed_provider_key"], "local_mock")
        self.assertEqual(provider_item.detail["fallback_reason"], FALLBACK_REASON_ENTRA_NOT_CONFIGURED)
        self.assertTrue(provider_item.detail["provider_is_mock_result"])


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

        for response in (results_response, bundles_response, status_response):
            self.assertEqual(response.status_code, 410)
            self.assertIn("processing-only", response.json()["detail"])

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

        for response in (results_response, bundles_response, status_response):
            self.assertEqual(response.status_code, 410)
            self.assertIn("processing-only", response.json()["detail"])

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
