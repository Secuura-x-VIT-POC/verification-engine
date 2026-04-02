import os
import sys
import unittest


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.trust.trust_engine import evaluate_trust


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
        self.assertEqual(result["reason_codes"], ["CONNECTOR_VERIFIED"])
        self.assertEqual(result["connector_ids"], ["vit_registry"])

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
        self.assertEqual(result["reason_codes"], ["CONNECTOR_MISMATCH"])

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
        self.assertEqual(result["reason_codes"], ["MISSING_REQUIRED_FIELD"])

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
        self.assertEqual(result["reason_codes"], ["CONNECTOR_TIMEOUT_REQUIRED"])

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
        self.assertEqual(result["reason_codes"], ["NOT_VERIFIED"])


if __name__ == "__main__":
    unittest.main()
