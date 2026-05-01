import json
import os
import sys
import unittest


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.trust.trust_engine import evaluate_trust
from backend.app.trust.trust_engine import _normalize_verifier_results


class TrustEngineTests(unittest.TestCase):
    def setUp(self):
        self.base_extraction = {
            "fields": {
                "name": "Kanak",
                "institution": "VIT",
                "credential": "BTech",
                "id": "ABC1234567",
            },
            "confidence": {
                "name": 0.98,
                "institution": 0.96,
                "credential": 0.95,
                "id": 0.94,
            },
            "bounding_boxes": {
                "name": {"page": 1, "x0": 10, "y0": 10, "x1": 60, "y1": 20},
                "institution": {"page": 1, "x0": 10, "y0": 30, "x1": 60, "y1": 40},
                "credential": {"page": 1, "x0": 10, "y0": 50, "x1": 60, "y1": 60},
                "id": {"page": 1, "x0": 10, "y0": 70, "x1": 60, "y1": 80},
            },
            "ocr_used": False,
        }
        self.base_policy = {
            "required_fields": ["name", "institution", "credential", "id"],
            "min_confidence_threshold": 0.8,
            "require_connector": True,
        }

    def test_full_green_path(self):
        result = evaluate_trust(
            self.base_extraction,
            {
                "connector_id": "vit_registry",
                "status": "VERIFIED",
                "reason_codes": ["REGISTRY_MATCH"],
                "assurance_class": "HIGH",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "GREEN")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["connector_ids"], ["vit_registry"])

    def test_list_shaped_connector_response_preserves_green_path(self):
        result = evaluate_trust(
            self.base_extraction,
            [
                {
                    "connector_id": "vit_registry",
                    "status": "VERIFIED",
                    "reason_codes": ["REGISTRY_MATCH"],
                    "assurance_class": "HIGH",
                }
            ],
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "GREEN")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["connector_ids"], ["vit_registry"])

    def test_missing_verifier_requires_review(self):
        policy = {
            **self.base_policy,
            "require_connector": False,
        }
        result = evaluate_trust(self.base_extraction, None, policy)

        self.assertEqual(result["outcome"], "AMBER")
        self.assertEqual(result["reason_codes"], ["LOW_CONFIDENCE_REVIEW_REQUIRED"])
        self.assertEqual(result["connector_ids"], [])

    def test_mismatch_returns_red(self):
        result = evaluate_trust(
            self.base_extraction,
            {
                "connector_id": "vit_registry",
                "status": "MISMATCH",
                "reason_codes": ["NAME_MISMATCH"],
                "assurance_class": "HIGH",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "RED")
        self.assertEqual(result["reason_codes"], ["NAME_MISMATCH"])

    def test_missing_field_returns_red(self):
        extraction = {
            **self.base_extraction,
            "fields": {
                "name": "Kanak",
                "institution": "VIT",
                "credential": "BTech",
            },
        }

        result = evaluate_trust(
            extraction,
            {
                "connector_id": "vit_registry",
                "status": "VERIFIED",
                "reason_codes": ["REGISTRY_MATCH"],
                "assurance_class": "HIGH",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "RED")
        self.assertEqual(result["reason_codes"], ["MISSING_MANDATORY_FIELD"])

    def test_high_assurance_timeout_returns_red(self):
        result = evaluate_trust(
            self.base_extraction,
            {
                "connector_id": "vit_registry",
                "status": "TIMEOUT",
                "reason_codes": ["CONNECTOR_TIMEOUT"],
                "assurance_class": "HIGH",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "RED")
        self.assertEqual(result["reason_codes"], ["CONNECTOR_TIMEOUT"])

    def test_optional_timeout_returns_amber(self):
        policy = {
            **self.base_policy,
            "require_connector": False,
        }
        result = evaluate_trust(
            self.base_extraction,
            {
                "connector_id": "vit_registry",
                "status": "TIMEOUT",
                "reason_codes": ["CONNECTOR_TIMEOUT"],
                "assurance_class": "OPTIONAL",
            },
            policy,
        )

        self.assertEqual(result["outcome"], "AMBER")
        self.assertEqual(result["reason_codes"], ["CONNECTOR_TIMEOUT"])

    def test_task_result_mismatch_handoff_forces_red(self):
        result = evaluate_trust(
            self.base_extraction,
            {
                "task_id": "task-name",
                "credential_id": "name",
                "executed_provider_key": "local_mock",
                "task_status": "SUCCEEDED",
                "audit_status": "MISMATCH",
                "outcome_color": "red",
                "reason_codes": ["PROVIDER_MISMATCH"],
                "explanation": "Provider found contradictory evidence.",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "RED")
        self.assertEqual(result["reason_codes"], ["PROVIDER_MISMATCH"])
        self.assertEqual(result["connector_ids"], ["local_mock"])

    def test_manual_review_task_result_handoff_remains_amber(self):
        result = evaluate_trust(
            self.base_extraction,
            {
                "task_id": "task-name",
                "credential_id": "name",
                "verifier_key": "manual_review",
                "task_status": "MANUAL_REVIEW",
                "audit_status": "MANUAL_REVIEW",
                "outcome_color": "amber",
                "reason_codes": ["NO_PROVIDER_AVAILABLE"],
                "explanation": "Manual review required.",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "AMBER")
        self.assertEqual(result["reason_codes"], ["NO_PROVIDER_AVAILABLE"])
        self.assertEqual(result["connector_ids"], ["manual_review"])

    def test_ai_only_high_confidence_cannot_create_green_without_verifier(self):
        extraction = {
            "fields": {
                "name": "RAW_TRUST_HANDOFF_SECRET_123",
                "institution": "Issuer",
                "credential": "Credential",
                "id": "ABC1234567",
            },
            "confidence": {
                "name": 1.0,
                "institution": 1.0,
                "credential": 1.0,
                "id": 1.0,
            },
        }

        result = evaluate_trust(extraction, None, self.base_policy)

        self.assertEqual(result["outcome"], "AMBER")
        self.assertTrue(result["reason_codes"])
        self.assertNotEqual(result["outcome"], "GREEN")

    def test_malformed_provider_result_normalizes_to_safe_non_green(self):
        malformed = {
            "task_id": "task-malformed",
            "field_id": "name",
            "connector_id": "local_mock",
            "status": "NOT_A_REAL_STATUS",
            "verification_confidence": "not-a-number",
            "reason_codes": [],
            "raw_provider_body": "RAW_PROVIDER_BODY_SECRET_123",
        }

        result = evaluate_trust(self.base_extraction, malformed, self.base_policy)
        normalized = _normalize_verifier_results(malformed)[0]
        serialized = json.dumps(normalized.model_dump(mode="json"), sort_keys=True)

        self.assertEqual(result["outcome"], "AMBER")
        self.assertIn("PROVIDER_RESULT_MALFORMED", result["reason_codes"])
        self.assertEqual(normalized.status, "ERROR")
        self.assertEqual(normalized.connector_id, "local_mock")
        self.assertEqual(normalized.task_id, "task-malformed")
        self.assertEqual(normalized.field_id, "name")
        self.assertNotIn("RAW_PROVIDER_BODY_SECRET_123", serialized)

    def test_normalized_handoff_preserves_safe_ids_and_reason_codes_only(self):
        raw = {
            "task_id": "task-secret",
            "credential_id": "name",
            "executed_provider_key": "local_mock",
            "task_status": "SUCCEEDED",
            "audit_status": "MISMATCH",
            "reason_codes": ["VERIFIER_MISMATCH"],
            "explanation": "Mismatch without raw values.",
            "matched_fields": {"name": "RAW_CREDENTIAL_VALUE_SECRET_123"},
            "raw_result_summary": {
                "raw_provider_body": "RAW_PROVIDER_BODY_SECRET_123",
                "gemini_raw_response": "RAW_GEMINI_SECRET_123",
            },
        }

        normalized = _normalize_verifier_results(raw)[0]
        serialized = json.dumps(normalized.model_dump(mode="json"), sort_keys=True)

        self.assertEqual(normalized.task_id, "task-secret")
        self.assertEqual(normalized.field_id, "name")
        self.assertEqual(normalized.connector_id, "local_mock")
        self.assertEqual(normalized.reason_codes, ["VERIFIER_MISMATCH"])
        self.assertEqual(normalized.status, "MISMATCH")
        self.assertNotIn("RAW_CREDENTIAL_VALUE_SECRET_123", serialized)
        self.assertNotIn("RAW_PROVIDER_BODY_SECRET_123", serialized)
        self.assertNotIn("RAW_GEMINI_SECRET_123", serialized)

    def test_task_result_verified_green_path_remains_valid(self):
        result = evaluate_trust(
            self.base_extraction,
            {
                "task_id": "task-name",
                "credential_id": "name",
                "executed_provider_key": "local_mock",
                "task_status": "SUCCEEDED",
                "audit_status": "VERIFIED",
                "outcome_color": "green",
                "confidence": 0.99,
                "reason_codes": ["PROVIDER_VERIFIED"],
                "explanation": "Local mock provider verified the field.",
            },
            self.base_policy,
        )

        self.assertEqual(result["outcome"], "GREEN")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["connector_ids"], ["local_mock"])


if __name__ == "__main__":
    unittest.main()
