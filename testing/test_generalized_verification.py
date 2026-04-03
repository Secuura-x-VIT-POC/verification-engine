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
from backend.app.verification_domain import (
    ANALYSIS_STATUS_PLAN_BUILT,
    ANALYSIS_STATUS_READY,
    AUDIT_STATUS_NOT_APPLICABLE,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    CredentialAudit,
    CredentialAuditCollection,
    DocumentProfile,
    DocumentVerificationSummary,
    ExtractedCredential,
    RuleBasedVerifierRouter,
    SessionCredentialCollection,
    VerificationTask,
    adapt_session_to_credential_audits,
    adapt_session_to_credentials,
    adapt_session_to_verification_plan,
    adapt_session_to_verification_summary,
    build_and_persist_final_analysis,
    build_and_persist_initial_analysis,
    build_extracted_credentials,
    build_verification_summary,
    get_analysis_status_for_session,
)


def _dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="python")
    return model.dict()


def _sample_extraction_payload() -> dict:
    return {
        "document_type": "academic_credential",
        "page_count": 2,
        "used_ocr": False,
        "field_details": [
            {
                "key": "name",
                "label": "Candidate Name",
                "value": "Kanak Sharma",
                "confidence": 0.98,
                "bounding_boxes": [{"page": 1, "x0": 10, "y0": 10, "x1": 80, "y1": 20}],
            },
            {
                "key": "institution",
                "label": "Institution",
                "value": "VIT Vellore",
                "confidence": 0.97,
                "bounding_boxes": [{"page": 1, "x0": 10, "y0": 25, "x1": 120, "y1": 35}],
            },
            {
                "key": "credential",
                "label": "Credential",
                "value": "BTech",
                "confidence": 0.96,
                "bounding_boxes": [{"page": 1, "x0": 10, "y0": 40, "x1": 90, "y1": 50}],
            },
            {
                "key": "document_id",
                "label": "Document ID",
                "value": "22BCE1234",
                "confidence": 0.95,
                "bounding_boxes": [{"page": 1, "x0": 10, "y0": 55, "x1": 90, "y1": 65}],
            },
            {
                "key": "issue_date",
                "label": "Issue Date",
                "value": "2024-06-15",
                "confidence": 0.91,
                "bounding_boxes": [{"page": 1, "x0": 10, "y0": 70, "x1": 90, "y1": 80}],
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


class GeneralizedVerificationPlannerTests(unittest.TestCase):
    def test_build_extracted_credentials_classifies_fields_and_flags_verification(self):
        extraction_payload = {
            "document_type": "mixed_document",
            "fields": {
                "full_name": "Asha Rao",
                "home_address": "221B Baker Street",
                "passport_number": "P1234567",
                "issue_date": "2026-01-10",
                "misc_note": "Boarded successfully",
            },
            "confidence": {
                "full_name": 0.99,
                "home_address": 0.94,
                "passport_number": 0.91,
                "issue_date": 0.85,
                "misc_note": 0.5,
            },
        }

        credentials = build_extracted_credentials(extraction_payload)
        categories = {credential.label: credential.category for credential in credentials}
        requirements = {credential.label: credential.requires_verification for credential in credentials}
        pii_flags = {credential.label: credential.is_pii for credential in credentials}

        self.assertEqual(categories["Full Name"], "identity")
        self.assertEqual(categories["Home Address"], "address")
        self.assertEqual(categories["Passport Number"], "passport")
        self.assertEqual(categories["Issue Date"], "unknown")
        self.assertTrue(requirements["Full Name"])
        self.assertTrue(requirements["Passport Number"])
        self.assertFalse(requirements["Issue Date"])
        self.assertFalse(requirements["Misc Note"])
        self.assertTrue(pii_flags["Full Name"])
        self.assertTrue(pii_flags["Home Address"])


class GeneralizedVerificationRoutingTests(unittest.TestCase):
    def test_rule_based_router_maps_known_and_unknown_credentials(self):
        router_impl = RuleBasedVerifierRouter()
        academic = ExtractedCredential(
            credential_id="credential-1",
            label="Degree",
            category="academic",
            value="BTech",
            normalized_value="BTech",
            requires_verification=True,
        )
        unknown = ExtractedCredential(
            credential_id="credential-2",
            label="Opaque Identifier",
            category="unknown",
            value="ZX-42",
            normalized_value="ZX-42",
            requires_verification=True,
        )

        academic_decision = router_impl.route(academic)
        unknown_decision = router_impl.route(unknown)

        self.assertEqual(academic_decision.selected_verifier_key, "academic_registry")
        self.assertFalse(academic_decision.manual_review_recommended)
        self.assertEqual(unknown_decision.selected_verifier_key, "manual_review")
        self.assertTrue(unknown_decision.manual_review_recommended)


class GeneralizedVerificationContractTests(unittest.TestCase):
    def test_contract_models_serialize_cleanly(self):
        credential = ExtractedCredential(
            credential_id="credential-1",
            label="Passport Number",
            category="passport",
            value="P1234567",
            normalized_value="P1234567",
            source_text="Passport No: P1234567",
            confidence=0.93,
            page=1,
            is_pii=True,
            requires_verification=True,
            verification_reason="Category 'passport' is mapped to a deterministic verifier route.",
            extraction_method="ocr",
        )
        task = VerificationTask(
            task_id="verify-credential-1",
            credential_id="credential-1",
            verifier_key="passport_db",
            verifier_label="Passport Database",
            verification_type="passport",
            required=True,
            status="PLANNED",
            reason_codes=["CATEGORY_PASSPORT", "AUTO_ROUTED"],
            input_payload={"normalized_value": "P1234567"},
        )
        summary = DocumentVerificationSummary(
            session_id="session-1",
            document_type="passport_document",
            total_credentials_found=1,
            total_credentials_verified=1,
            green_count=1,
            overall_outcome="GREEN",
            overall_reason_codes=["CONNECTOR_VERIFIED"],
        )
        audit = CredentialAudit(
            credential_id="credential-1",
            label="Passport Number",
            document_value="P1234567",
            normalized_value="P1234567",
            verifier_label="Passport Database",
            audit_status="VERIFIED",
            outcome_color="green",
            explanation="Matched against current connector evidence.",
            reason_codes=["CONNECTOR_VERIFIED"],
            timestamp=datetime.utcnow(),
        )
        profile = DocumentProfile(
            session_id="session-1",
            document_type="passport_document",
            document_family="identity_document",
            page_count=1,
            extraction_methods_used=["ocr"],
            pii_detected=True,
            detected_categories=["passport"],
            requires_manual_review=False,
            notes=[],
        )

        credential_payload = _dump_model(credential)
        task_payload = _dump_model(task)
        summary_payload = _dump_model(summary)
        audit_payload = _dump_model(audit)
        profile_payload = _dump_model(profile)

        self.assertEqual(credential_payload["label"], "Passport Number")
        self.assertEqual(task_payload["verifier_key"], "passport_db")
        self.assertEqual(summary_payload["overall_outcome"], "GREEN")
        self.assertEqual(audit_payload["audit_status"], "VERIFIED")
        self.assertEqual(profile_payload["document_family"], "identity_document")


class GeneralizedVerificationAdapterTests(unittest.TestCase):
    def test_adapters_convert_existing_session_shapes_into_generalized_models(self):
        session = SessionModel(
            id="session-adapter",
            user_id="user-1",
            status=SessionState.VERIFIED_GREEN,
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            verified_at=datetime.utcnow(),
        )

        credentials = adapt_session_to_credentials(session)
        plan = adapt_session_to_verification_plan(session)
        audits = adapt_session_to_credential_audits(session)
        summary = adapt_session_to_verification_summary(session)

        self.assertEqual(credentials.document_type, "academic_credential")
        self.assertEqual(len(credentials.credentials), 5)
        self.assertEqual(len(plan.tasks), 4)
        self.assertEqual(summary.overall_outcome, "GREEN")
        self.assertEqual(summary.green_count, 4)
        self.assertEqual(summary.total_credentials_found, 5)

        audits_by_label = {audit.label: audit for audit in audits.audits}
        self.assertEqual(audits_by_label["Candidate Name"].audit_status, "VERIFIED")
        self.assertEqual(audits_by_label["Credential"].audit_status, "VERIFIED")
        self.assertEqual(audits_by_label["Document ID"].audit_status, "VERIFIED")
        self.assertEqual(audits_by_label["Issue Date"].audit_status, AUDIT_STATUS_NOT_APPLICABLE)


class GeneralizedVerificationServiceTests(unittest.TestCase):
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

    def test_two_pass_analysis_persists_artifacts_on_session_row(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-persisted",
            user_id="user-1",
            status=SessionState.VERIFIED_GREEN,
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            verified_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        build_and_persist_initial_analysis(session)
        db.commit()
        db.refresh(session)

        self.assertEqual(session.generalized_analysis_status, ANALYSIS_STATUS_PLAN_BUILT)
        self.assertIsNotNone(session.document_profile_payload)
        self.assertIsNotNone(session.generalized_credentials_payload)
        self.assertIsNotNone(session.verification_plan_payload)
        self.assertIsNone(session.credential_audits_payload)
        self.assertIsNone(session.verification_summary_payload)

        build_and_persist_final_analysis(session)
        db.commit()
        db.refresh(session)

        self.assertEqual(session.generalized_analysis_status, ANALYSIS_STATUS_READY)
        self.assertEqual(session.verification_execution_status, "READY")
        self.assertIsNotNone(session.verification_task_results_payload)
        self.assertIsNotNone(session.credential_verification_bundles_payload)
        self.assertIsNotNone(session.verification_execution_summary_payload)
        self.assertIsNotNone(session.credential_audits_payload)
        self.assertIsNotNone(session.verification_summary_payload)
        self.assertEqual(session.verification_summary_payload["green_count"], 4)
        self.assertEqual(session.document_profile_payload["document_family"], "academic_document")
        db.close()

    def test_summary_counts_are_derived_from_bounded_audit_statuses(self):
        audits = CredentialAuditCollection(
            session_id="session-summary",
            document_type="mixed_document",
            audits=[
                CredentialAudit(
                    credential_id="c1",
                    label="One",
                    verifier_label="Verifier",
                    audit_status="VERIFIED",
                    outcome_color="green",
                    explanation="Matched",
                ),
                CredentialAudit(
                    credential_id="c2",
                    label="Two",
                    verifier_label="Verifier",
                    audit_status="MISMATCH",
                    outcome_color="red",
                    explanation="Mismatch",
                ),
                CredentialAudit(
                    credential_id="c3",
                    label="Three",
                    verifier_label="Verifier",
                    audit_status="PARTIAL",
                    outcome_color="amber",
                    explanation="Partial",
                ),
                CredentialAudit(
                    credential_id="c4",
                    label="Four",
                    verifier_label="Verifier",
                    audit_status="UNVERIFIED",
                    outcome_color="amber",
                    explanation="Unverified",
                ),
                CredentialAudit(
                    credential_id="c5",
                    label="Five",
                    verifier_label="Verifier",
                    audit_status="MANUAL_REVIEW",
                    outcome_color="amber",
                    explanation="Manual review",
                ),
                CredentialAudit(
                    credential_id="c6",
                    label="Six",
                    verifier_label="Verifier",
                    audit_status="NOT_APPLICABLE",
                    outcome_color="neutral",
                    explanation="N/A",
                ),
            ],
        )
        credentials = SessionCredentialCollection(
            session_id="session-summary",
            document_type="mixed_document",
            credentials=[
                ExtractedCredential(credential_id="c1", label="One", category="identity"),
                ExtractedCredential(credential_id="c2", label="Two", category="identity"),
                ExtractedCredential(credential_id="c3", label="Three", category="identity"),
                ExtractedCredential(credential_id="c4", label="Four", category="identity"),
                ExtractedCredential(credential_id="c5", label="Five", category="identity"),
                ExtractedCredential(credential_id="c6", label="Six", category="identity"),
            ],
        )

        summary = build_verification_summary(
            "session-summary",
            {"document_type": "mixed_document"},
            credential_audits=audits,
            trust_outcome=None,
            reason_codes=["NOT_VERIFIED"],
            credentials=credentials,
        )

        self.assertEqual(summary.green_count, 1)
        self.assertEqual(summary.red_count, 1)
        self.assertEqual(summary.amber_count, 3)
        self.assertEqual(summary.manual_review_count, 1)
        self.assertEqual(summary.total_credentials_verified, 3)

    def test_missing_connector_evidence_results_in_unverified_and_partial_statuses(self):
        base_kwargs = {
            "user_id": "user-1",
            "status": SessionState.VERIFIED_AMBER,
            "extraction_payload": _sample_extraction_payload(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        no_connector_session = SessionModel(
            id="session-unverified",
            connector_payload=[],
            reason_codes=[],
            **base_kwargs,
        )
        partial_session = SessionModel(
            id="session-partial",
            connector_payload=[
                {
                    "connector_id": "vit_registry",
                    "status": "TIMEOUT",
                    "reason_codes": ["CONNECTOR_TIMEOUT"],
                    "matched_claims": {},
                    "mismatched_claims": {},
                    "assurance_class": "HIGH",
                }
            ],
            reason_codes=["CONNECTOR_TIMEOUT_REQUIRED"],
            **base_kwargs,
        )

        unverified_audits = adapt_session_to_credential_audits(no_connector_session)
        partial_audits = adapt_session_to_credential_audits(partial_session)

        unverified_by_label = {audit.label: audit for audit in unverified_audits.audits}
        partial_by_label = {audit.label: audit for audit in partial_audits.audits}

        self.assertEqual(unverified_by_label["Candidate Name"].audit_status, AUDIT_STATUS_UNVERIFIED)
        self.assertEqual(partial_by_label["Candidate Name"].audit_status, AUDIT_STATUS_PARTIAL)
        self.assertEqual(partial_by_label["Issue Date"].audit_status, AUDIT_STATUS_NOT_APPLICABLE)

    def test_analysis_status_is_inferred_for_legacy_rows_without_persisted_payloads(self):
        session = SessionModel(
            id="session-legacy",
            user_id="user-1",
            status=SessionState.VERIFIED_GREEN,
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            verified_at=datetime.utcnow(),
        )

        payload = get_analysis_status_for_session(session)

        self.assertEqual(payload.generalized_analysis_status, ANALYSIS_STATUS_READY)
        self.assertIsNone(payload.generalized_analysis_error)
        self.assertTrue(payload.document_profile_available)
        self.assertTrue(payload.verification_summary_available)


class GeneralizedVerificationApiTests(unittest.TestCase):
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

    def test_new_endpoints_return_safe_structures_when_no_generalized_data_exists(self):
        self._create_session(
            session_id="session-empty-generalized",
            status=SessionState.CREATED,
            user_id="user-1",
        )

        credentials_response = self.client.get("/session/session-empty-generalized/credentials")
        plan_response = self.client.get("/session/session-empty-generalized/verification-plan")
        audits_response = self.client.get("/session/session-empty-generalized/credential-audits")
        summary_response = self.client.get("/session/session-empty-generalized/verification-summary")
        profile_response = self.client.get("/session/session-empty-generalized/document-profile")
        analysis_status_response = self.client.get("/session/session-empty-generalized/analysis-status")

        self.assertEqual(credentials_response.status_code, 200)
        self.assertEqual(plan_response.status_code, 200)
        self.assertEqual(audits_response.status_code, 200)
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(analysis_status_response.status_code, 200)

        self.assertEqual(
            credentials_response.json(),
            {
                "session_id": "session-empty-generalized",
                "document_type": "unknown",
                "credentials": [],
            },
        )
        self.assertEqual(
            plan_response.json(),
            {
                "session_id": "session-empty-generalized",
                "document_type": "unknown",
                "route_decisions": [],
                "tasks": [],
            },
        )
        self.assertEqual(
            audits_response.json(),
            {
                "session_id": "session-empty-generalized",
                "document_type": "unknown",
                "audits": [],
            },
        )
        self.assertEqual(
            summary_response.json(),
            {
                "session_id": "session-empty-generalized",
                "document_type": "unknown",
                "total_credentials_found": 0,
                "total_credentials_verified": 0,
                "green_count": 0,
                "amber_count": 0,
                "red_count": 0,
                "manual_review_count": 0,
                "overall_outcome": None,
                "overall_reason_codes": [],
            },
        )
        self.assertEqual(
            profile_response.json(),
            {
                "session_id": "session-empty-generalized",
                "document_type": "unknown",
                "document_family": "unknown",
                "page_count": None,
                "extraction_methods_used": [],
                "pii_detected": False,
                "detected_categories": [],
                "requires_manual_review": False,
                "notes": [],
            },
        )
        self.assertEqual(
            analysis_status_response.json(),
            {
                "session_id": "session-empty-generalized",
                "workflow_state": SessionState.CREATED,
                "generalized_analysis_status": "NOT_STARTED",
                "generalized_analysis_error": None,
                "document_profile_available": False,
                "credentials_available": False,
                "verification_plan_available": False,
                "credential_audits_available": False,
                "verification_summary_available": False,
            },
        )

    def test_endpoints_prefer_persisted_generalized_artifacts_when_present(self):
        self._create_session(
            session_id="session-persisted-summary",
            status=SessionState.VERIFIED_GREEN,
            user_id="user-1",
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            verification_summary_payload={
                "session_id": "session-persisted-summary",
                "document_type": "persisted_document",
                "total_credentials_found": 7,
                "total_credentials_verified": 5,
                "green_count": 4,
                "amber_count": 1,
                "red_count": 0,
                "manual_review_count": 0,
                "overall_outcome": "GREEN",
                "overall_reason_codes": ["PERSISTED_SUMMARY"],
            },
            document_profile_payload={
                "session_id": "session-persisted-summary",
                "document_type": "persisted_document",
                "document_family": "mixed_document",
                "page_count": 9,
                "extraction_methods_used": ["persisted_method"],
                "pii_detected": True,
                "detected_categories": ["identity", "academic"],
                "requires_manual_review": False,
                "notes": ["persisted"],
            },
            generalized_analysis_status=ANALYSIS_STATUS_READY,
        )

        summary_response = self.client.get("/session/session-persisted-summary/verification-summary")
        profile_response = self.client.get("/session/session-persisted-summary/document-profile")

        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(summary_response.json()["document_type"], "persisted_document")
        self.assertEqual(summary_response.json()["overall_reason_codes"], ["PERSISTED_SUMMARY"])
        self.assertEqual(profile_response.json()["page_count"], 9)
        self.assertEqual(profile_response.json()["notes"], ["persisted"])

    def test_analysis_status_endpoint_infers_ready_for_legacy_verified_sessions(self):
        self._create_session(
            session_id="session-legacy-analysis",
            status=SessionState.VERIFIED_GREEN,
            user_id="user-1",
            extraction_payload=_sample_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
        )

        response = self.client.get("/session/session-legacy-analysis/analysis-status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["generalized_analysis_status"], ANALYSIS_STATUS_READY)
        self.assertTrue(response.json()["document_profile_available"])
        self.assertTrue(response.json()["verification_summary_available"])

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
        extraction_payload: dict | None = None,
        connector_payload: list[dict] | None = None,
        trust_outcome: str | None = None,
        reason_codes: list[str] | None = None,
        verification_summary_payload: dict | None = None,
        document_profile_payload: dict | None = None,
        generalized_analysis_status: str | None = None,
    ) -> None:
        db = self.SessionLocal()
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            status=status,
            trust_outcome=trust_outcome,
            reason_codes=reason_codes or [],
            connector_ids=[],
            extraction_payload=extraction_payload,
            connector_payload=connector_payload,
            verification_summary_payload=verification_summary_payload,
            document_profile_payload=document_profile_payload,
            generalized_analysis_status=generalized_analysis_status,
        )
        db.add(session)
        db.commit()
        db.close()


if __name__ == "__main__":
    unittest.main()
