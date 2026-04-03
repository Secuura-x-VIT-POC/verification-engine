import os
import sys
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
    get_credentials_for_session,
    get_credential_audits_for_session,
    get_verification_summary_for_session,
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
        "field_candidates": [
            {
                "candidate_id": "cand-name",
                "label": "Candidate Name",
                "category": "person_name",
                "raw_value": "Kanak Sharma",
                "normalized_value": "Kanak Sharma",
                "source_text": "Student Name: Kanak Sharma",
                "confidence": 0.98,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 80, "y1": 20},
                "is_pii": True,
                "requires_verification": True,
                "verification_reason": "Identity claim",
                "extraction_method": "native_text",
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
                "verification_reason": "Academic issuer",
                "extraction_method": "native_text",
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
                "extraction_method": "native_text",
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
                "extraction_method": "native_text",
            },
            {
                "candidate_id": "cand-date",
                "label": "Issue Date",
                "category": "issue_date",
                "raw_value": "2024-06-15",
                "normalized_value": "2024-06-15",
                "source_text": "Issue Date: 2024-06-15",
                "confidence": 0.91,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 70, "x1": 90, "y1": 80},
                "is_pii": False,
                "requires_verification": False,
                "verification_reason": "Supporting metadata",
                "extraction_method": "native_text",
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
            "field_candidates": [
                {
                    "candidate_id": "cand-name",
                    "label": "Full Name",
                    "category": "person_name",
                    "raw_value": "Asha Rao",
                    "normalized_value": "Asha Rao",
                    "source_text": "Full Name: Asha Rao",
                    "confidence": 0.99,
                    "page": 1,
                    "is_pii": True,
                    "requires_verification": True,
                    "verification_reason": "Identity claim",
                },
                {
                    "candidate_id": "cand-address",
                    "label": "Home Address",
                    "category": "address",
                    "raw_value": "221B Baker Street",
                    "normalized_value": "221B Baker Street",
                    "source_text": "Home Address: 221B Baker Street",
                    "confidence": 0.94,
                    "page": 1,
                    "is_pii": True,
                    "requires_verification": True,
                    "verification_reason": "Address claim",
                },
                {
                    "candidate_id": "cand-passport",
                    "label": "Passport Number",
                    "category": "document_number",
                    "raw_value": "P1234567",
                    "normalized_value": "P1234567",
                    "source_text": "Passport Number: P1234567",
                    "confidence": 0.91,
                    "page": 1,
                    "is_pii": True,
                    "requires_verification": True,
                    "verification_reason": "Passport claim",
                },
                {
                    "candidate_id": "cand-date",
                    "label": "Issue Date",
                    "category": "issue_date",
                    "raw_value": "2026-01-10",
                    "normalized_value": "2026-01-10",
                    "source_text": "Issue Date: 2026-01-10",
                    "confidence": 0.85,
                    "page": 1,
                    "is_pii": False,
                    "requires_verification": False,
                    "verification_reason": "Supporting metadata",
                },
                {
                    "candidate_id": "cand-note",
                    "label": "Misc Note",
                    "category": "unknown",
                    "raw_value": "Boarded successfully",
                    "normalized_value": "Boarded successfully",
                    "source_text": "Misc Note: Boarded successfully",
                    "confidence": 0.5,
                    "page": 1,
                    "is_pii": False,
                    "requires_verification": False,
                    "verification_reason": "No route",
                },
            ],
        }

        credentials = build_extracted_credentials(extraction_payload)
        categories = {credential.label: credential.category for credential in credentials}
        requirements = {credential.label: credential.requires_verification for credential in credentials}
        pii_flags = {credential.label: credential.is_pii for credential in credentials}

        self.assertEqual(categories["Full Name"], "identity")
        self.assertEqual(categories["Address"], "address")
        self.assertEqual(categories["Passport Number"], "passport")
        self.assertTrue(requirements["Full Name"])
        self.assertTrue(requirements["Passport Number"])
        self.assertTrue(pii_flags["Full Name"])
        self.assertTrue(pii_flags["Address"])
        self.assertNotIn("Issue Date", categories)
        self.assertNotIn("Misc Note", categories)

    def test_build_extracted_credentials_ignores_legacy_field_details_without_generalized_candidates(self):
        credentials = build_extracted_credentials(
            {
                "document_type": "academic_credential",
                "field_details": [
                    {
                        "key": "name",
                        "label": "Candidate Name",
                        "value": None,
                        "confidence": 0,
                        "bounding_boxes": [],
                    }
                ],
            }
        )

        self.assertEqual(credentials, [])

    def test_report_card_identifier_fields_are_classified_as_academic(self):
        extraction_payload = {
            "document_type": "report_card",
            "field_candidates": [
                {
                    "candidate_id": "cand-student",
                    "label": "Student Name",
                    "category": "person_name",
                    "raw_value": "Demo Student",
                    "normalized_value": "Demo Student",
                    "source_text": "Student Name: Demo Student",
                    "confidence": 0.94,
                    "page": 1,
                    "is_pii": True,
                    "requires_verification": True,
                    "verification_reason": "Student identity",
                },
                {
                    "candidate_id": "cand-roll",
                    "label": "Roll Number",
                    "category": "registration_number",
                    "raw_value": "RC2026001",
                    "normalized_value": "RC2026001",
                    "source_text": "Roll Number: RC2026001",
                    "confidence": 0.95,
                    "page": 1,
                    "requires_verification": True,
                    "verification_reason": "Academic identifier",
                },
                {
                    "candidate_id": "cand-date",
                    "label": "Issue Date",
                    "category": "issue_date",
                    "raw_value": "2026-03-10",
                    "normalized_value": "2026-03-10",
                    "source_text": "Issue Date: 2026-03-10",
                    "confidence": 0.82,
                    "page": 1,
                    "requires_verification": False,
                    "verification_reason": "Supporting metadata",
                },
            ],
        }

        credentials = build_extracted_credentials(extraction_payload)
        categories = {credential.label: credential.category for credential in credentials}
        requirements = {credential.label: credential.requires_verification for credential in credentials}

        self.assertEqual(categories["Roll Number"], "academic")
        self.assertTrue(requirements["Roll Number"])
        self.assertEqual(categories["Student Name"], "academic")

    def test_generic_name_and_issuer_are_demoted_until_grouped(self):
        session = SessionModel(
            id="session-planner-context",
            user_id="user-1",
            status=SessionState.VERIFIED_AMBER,
            extraction_payload={
                "document_type": "generic_document",
                "field_candidates": [
                    {
                        "candidate_id": "cand-name",
                        "label": "Name",
                        "category": "person_name",
                        "raw_value": "Asha Rao",
                        "normalized_value": "Asha Rao",
                        "source_text": "Name: Asha Rao",
                        "confidence": 0.96,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 80, "y1": 20},
                    },
                    {
                        "candidate_id": "cand-issuer",
                        "label": "Issuer",
                        "category": "issuer",
                        "raw_value": "Demo Authority",
                        "normalized_value": "Demo Authority",
                        "source_text": "Issuer: Demo Authority",
                        "confidence": 0.94,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 22, "x1": 90, "y1": 32},
                    },
                    {
                        "candidate_id": "cand-title",
                        "label": "Credential",
                        "category": "credential_title",
                        "raw_value": "Identity Card",
                        "normalized_value": "Identity Card",
                        "source_text": "Credential: Identity Card",
                        "confidence": 0.92,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 34, "x1": 90, "y1": 44},
                    },
                ],
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        collection = adapt_session_to_credentials(session)

        self.assertEqual(collection.credentials, [])
        context_by_label = {credential.label: credential for credential in collection.context_fields}
        self.assertEqual(context_by_label["Name"].planning_status, "context_only")
        self.assertEqual(context_by_label["Issuer"].planning_status, "context_only")
        self.assertEqual(context_by_label["Credential Title"].planning_status, "context_only")

    def test_grouping_promotes_academic_identity_and_demotes_credential_title(self):
        session = SessionModel(
            id="session-planner-grouping",
            user_id="user-1",
            status=SessionState.VERIFIED_AMBER,
            extraction_payload=_sample_extraction_payload(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        collection = adapt_session_to_credentials(session)
        credentials_by_label = {credential.label: credential for credential in collection.credentials}
        context_by_label = {credential.label: credential for credential in collection.context_fields}

        self.assertEqual(sorted(credentials_by_label), ["Institution Name", "Roll Number", "Student Name"])
        self.assertEqual(credentials_by_label["Student Name"].category, "academic")
        self.assertEqual(credentials_by_label["Institution Name"].category, "academic")
        self.assertEqual(credentials_by_label["Roll Number"].category, "academic")
        self.assertEqual(context_by_label["Credential Title"].planning_status, "context_only")
        self.assertEqual(context_by_label["Issue Date"].planning_status, "metadata_only")

    def test_identity_specific_fields_are_promoted_when_strong(self):
        extraction_payload = {
            "document_type": "aadhaar_card",
            "field_candidates": [
                {
                    "candidate_id": "cand-name",
                    "label": "Name",
                    "category": "person_name",
                    "raw_value": "Asha Rao",
                    "normalized_value": "Asha Rao",
                    "source_text": "Name: Asha Rao",
                    "confidence": 0.98,
                    "page": 1,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 80, "y1": 20},
                },
                {
                    "candidate_id": "cand-dob",
                    "label": "Date of Birth",
                    "category": "date_of_birth",
                    "raw_value": "1997-05-12",
                    "normalized_value": "1997-05-12",
                    "source_text": "Date of Birth: 1997-05-12",
                    "confidence": 0.95,
                    "page": 1,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 22, "x1": 90, "y1": 32},
                },
                {
                    "candidate_id": "cand-aadhaar",
                    "label": "Aadhaar",
                    "category": "national_identifier",
                    "raw_value": "9999 8888 7777",
                    "normalized_value": "999988887777",
                    "source_text": "Aadhaar: 9999 8888 7777",
                    "confidence": 0.97,
                    "page": 1,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 34, "x1": 90, "y1": 44},
                },
                {
                    "candidate_id": "cand-pan",
                    "label": "PAN",
                    "category": "tax_identifier",
                    "raw_value": "ABCDE1234F",
                    "normalized_value": "ABCDE1234F",
                    "source_text": "PAN: ABCDE1234F",
                    "confidence": 0.97,
                    "page": 1,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 46, "x1": 90, "y1": 56},
                },
            ],
        }

        credentials = build_extracted_credentials(extraction_payload)
        credentials_by_label = {credential.label: credential for credential in credentials}

        self.assertEqual(credentials_by_label["Full Name"].category, "identity")
        self.assertEqual(credentials_by_label["Date of Birth"].category, "identity")
        self.assertEqual(credentials_by_label["Aadhaar Number"].category, "identity")
        self.assertEqual(credentials_by_label["PAN Number"].category, "tax")


class GeneralizedVerificationRoutingTests(unittest.TestCase):
    def test_rule_based_router_marks_entra_preference_with_local_fallback_by_default(self):
        router_impl = RuleBasedVerifierRouter()
        identity = ExtractedCredential(
            credential_id="credential-identity",
            label="Candidate Name",
            category="identity",
            value="Kanak Sharma",
            normalized_value="Kanak Sharma",
            requires_verification=True,
        )
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

        identity_decision = router_impl.route(identity)
        academic_decision = router_impl.route(academic)
        unknown_decision = router_impl.route(unknown)

        self.assertEqual(identity_decision.selected_verifier_key, "identity_db")
        self.assertEqual(identity_decision.preferred_provider_key, "entra_verified_id")
        self.assertEqual(identity_decision.planned_provider_key, "local_mock")
        self.assertEqual(academic_decision.selected_verifier_key, "academic_registry")
        self.assertEqual(academic_decision.preferred_provider_key, "entra_verified_id")
        self.assertFalse(academic_decision.manual_review_recommended)
        self.assertEqual(unknown_decision.selected_verifier_key, "manual_review")
        self.assertTrue(unknown_decision.manual_review_recommended)

    def test_rule_based_router_prefers_entra_when_enabled_and_uses_supplementary_when_not(self):
        identity = ExtractedCredential(
            credential_id="credential-identity",
            label="Candidate Name",
            category="identity",
            value="Kanak Sharma",
            normalized_value="Kanak Sharma",
            requires_verification=True,
        )

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
            entra_router = RuleBasedVerifierRouter()
            entra_decision = entra_router.route(identity)

        with patch.dict(
            os.environ,
            {
                "VERIFIER_EXTERNAL_PROVIDER_ENABLED": "1",
                "VERIFIER_ENABLED_PROVIDERS": "identity_http,local_mock",
                "VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_ENABLED": "0",
                "VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_BASE_URL": "https://entra.example.com",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_ENABLED": "1",
                "VERIFIER_PROVIDER_IDENTITY_HTTP_BASE_URL": "https://identity.example.com",
            },
            clear=False,
        ):
            supplementary_router = RuleBasedVerifierRouter()
            supplementary_decision = supplementary_router.route(identity)

        self.assertEqual(entra_decision.preferred_provider_key, "entra_verified_id")
        self.assertEqual(entra_decision.planned_provider_key, "entra_verified_id")
        self.assertIn("primary VC trust rail", entra_decision.route_reason)
        self.assertEqual(supplementary_decision.preferred_provider_key, "entra_verified_id")
        self.assertEqual(supplementary_decision.planned_provider_key, "identity_http")
        self.assertIn("supplementary provider", supplementary_decision.route_reason.lower())


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
        self.assertEqual(len(credentials.credentials), 3)
        self.assertEqual(len(credentials.context_fields), 2)
        self.assertEqual(len(plan.tasks), 3)
        self.assertEqual(summary.overall_outcome, "GREEN")
        self.assertEqual(summary.green_count, 3)
        self.assertEqual(summary.total_credentials_found, 3)

        audits_by_label = {audit.label: audit for audit in audits.audits}
        self.assertEqual(audits_by_label["Student Name"].audit_status, "VERIFIED")
        self.assertEqual(audits_by_label["Institution Name"].audit_status, "VERIFIED")
        self.assertEqual(audits_by_label["Roll Number"].audit_status, "VERIFIED")
        self.assertFalse(
            any(item.evidence_type == "trust_result" for item in audits_by_label["Student Name"].evidence)
        )
        self.assertTrue(
            any(item.evidence_type == "connector_claim_summary" for item in audits_by_label["Student Name"].evidence)
        )


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
        self.assertEqual(session.verification_summary_payload["green_count"], 3)
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

        self.assertEqual(unverified_by_label["Student Name"].audit_status, AUDIT_STATUS_UNVERIFIED)
        self.assertEqual(partial_by_label["Student Name"].audit_status, AUDIT_STATUS_PARTIAL)

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

    def test_persisted_placeholder_credentials_are_filtered_from_read_models(self):
        session = SessionModel(
            id="session-sanitized",
            user_id="user-1",
            status=SessionState.VERIFIED_AMBER,
            trust_outcome="AMBER",
            reason_codes=["NOT_VERIFIED"],
            extraction_payload={"document_type": "academic_credential", "field_candidates": []},
            generalized_credentials_payload={
                "session_id": "session-sanitized",
                "document_type": "academic_credential",
                "credentials": [
                    {
                        "credential_id": "legacy-empty",
                        "label": "Candidate Name",
                        "category": "identity",
                        "value": None,
                        "normalized_value": None,
                        "source_text": None,
                        "confidence": 0,
                        "page": None,
                        "bounding_box": None,
                        "is_pii": True,
                        "requires_verification": True,
                        "verification_reason": "Legacy placeholder",
                        "extraction_method": "legacy",
                    },
                    {
                        "credential_id": "real-id",
                        "label": "Document ID",
                        "category": "academic",
                        "value": "22BCE1234",
                        "normalized_value": "22BCE1234",
                        "source_text": "Document ID: 22BCE1234",
                        "confidence": 0.95,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 90, "y1": 20},
                        "is_pii": False,
                        "requires_verification": True,
                        "verification_reason": "Academic identifier",
                        "extraction_method": "native_text",
                    },
                ],
            },
            verification_plan_payload={
                "session_id": "session-sanitized",
                "document_type": "academic_credential",
                "route_decisions": [
                    {
                        "credential_id": "legacy-empty",
                        "selected_verifier_key": "identity_db",
                        "selected_verifier_label": "Identity Database",
                        "route_reason": "legacy",
                        "fallback_verifiers": [],
                        "manual_review_recommended": False,
                    },
                    {
                        "credential_id": "real-id",
                        "selected_verifier_key": "academic_registry",
                        "selected_verifier_label": "Academic Registry",
                        "route_reason": "academic",
                        "fallback_verifiers": [],
                        "manual_review_recommended": False,
                    },
                ],
                "tasks": [
                    {
                        "task_id": "task-legacy",
                        "credential_id": "legacy-empty",
                        "verifier_key": "identity_db",
                        "verifier_label": "Identity Database",
                        "verification_type": "identity",
                        "required": True,
                        "status": "PLANNED",
                        "reason_codes": [],
                        "input_payload": {},
                    },
                    {
                        "task_id": "task-real",
                        "credential_id": "real-id",
                        "verifier_key": "academic_registry",
                        "verifier_label": "Academic Registry",
                        "verification_type": "academic",
                        "required": True,
                        "status": "PLANNED",
                        "reason_codes": [],
                        "input_payload": {},
                    },
                ],
            },
            credential_audits_payload={
                "session_id": "session-sanitized",
                "document_type": "academic_credential",
                "audits": [
                    {
                        "credential_id": "legacy-empty",
                        "label": "Candidate Name",
                        "document_value": None,
                        "normalized_value": None,
                        "verifier_label": "Identity Database",
                        "audit_status": "UNVERIFIED",
                        "outcome_color": "amber",
                        "explanation": "Legacy placeholder",
                        "reason_codes": [],
                        "matched_fields": {},
                        "mismatched_fields": {},
                        "missing_fields": [],
                        "evidence": [],
                        "timestamp": None,
                    },
                    {
                        "credential_id": "real-id",
                        "label": "Document ID",
                        "document_value": "22BCE1234",
                        "normalized_value": "22BCE1234",
                        "verifier_label": "Academic Registry",
                        "audit_status": "UNVERIFIED",
                        "outcome_color": "amber",
                        "explanation": "Pending verification",
                        "reason_codes": [],
                        "matched_fields": {},
                        "mismatched_fields": {},
                        "missing_fields": [],
                        "evidence": [],
                        "timestamp": None,
                    },
                ],
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        credentials = get_credentials_for_session(session)
        audits = get_credential_audits_for_session(session)
        summary = get_verification_summary_for_session(session)

        self.assertEqual([credential.credential_id for credential in credentials.credentials], ["real-id"])
        self.assertEqual([audit.credential_id for audit in audits.audits], ["real-id"])
        self.assertEqual(summary.total_credentials_found, 1)


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
                "context_fields": [],
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
