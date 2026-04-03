import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.inference.nvidia import NvidiaInferenceError
from backend.app.workflow.runtime import extract_document_payload
from extraction.analysis.nvidia_enrichment import enrich_field_candidates_with_nvidia
from extraction.parser.document_parser import extract_document_data
from extraction.schema.models import BoundingBox, EvidenceLine, ExtractionWarning, FieldCandidate, SpatialTextToken


class ExtractionPipelineMergeTests(unittest.TestCase):
    def test_extract_document_data_returns_richer_candidates_and_legacy_schema_for_simple_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "identity_sample.pdf"
            _write_text_pdf(
                file_path,
                [
                    "Holder Name: Asha Rao",
                    "Aadhaar Number: 1234 5678 9012",
                    "Date of Birth: 01/02/2001",
                ],
            )

            result = extract_document_data(str(file_path))

        self.assertTrue(result.is_successful)
        self.assertFalse(result.used_ocr)
        self.assertIsNotNone(result.fields.candidate_name)
        self.assertEqual(result.fields.candidate_name.value, "Asha Rao")
        self.assertIsNotNone(result.fields.document_id)
        self.assertTrue(any(candidate.category == "person_name" for candidate in result.field_candidates))
        self.assertTrue(any(candidate.category == "national_identifier" for candidate in result.field_candidates))
        self.assertGreater(len(result.evidence_lines), 0)
        self.assertIsNotNone(result.metadata)
        self.assertIsNotNone(result.safety_report)
        self.assertEqual(result.metadata.page_count, 1)

    def test_extract_document_data_rejects_non_pdf_with_reason_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "not_a_pdf.txt"
            file_path.write_text("plain text", encoding="utf-8")

            result = extract_document_data(str(file_path))

        self.assertFalse(result.is_successful)
        self.assertEqual(result.reason_code, "UNSUPPORTED_FORMAT")
        self.assertEqual(result.raw_text, "")


class ExtractionRuntimeCompatibilityTests(unittest.TestCase):
    def test_extract_document_payload_uses_generalized_view_and_keeps_trust_aliases_isolated(self):
        raw_result = {
            "page_count": 1,
            "used_ocr": False,
            "raw_text": "Student Name: Riya Sen\nRoll Number: RC2026001\nGrade: A+\nInstitution: Demo Central School",
            "fields": {
                "candidate_name": {
                    "value": "Riya Sen",
                    "confidence": 0.97,
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 10, "x1": 110, "y1": 20}],
                },
                "institution": {
                    "value": "Demo Central School",
                    "confidence": 0.96,
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 30, "x1": 180, "y1": 40}],
                },
                "credential_type": {
                    "value": "Report Card",
                    "confidence": 0.95,
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 50, "x1": 120, "y1": 60}],
                },
                "document_id": {
                    "value": "RC2026001",
                    "confidence": 0.94,
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 70, "x1": 120, "y1": 80}],
                },
            },
            "field_candidates": [
                {
                    "candidate_id": "cand-name",
                    "label": "name",
                    "category": "person_name",
                    "raw_value": "Riya Sen",
                    "normalized_value": "Riya Sen",
                    "source_text": "Student Name: Riya Sen",
                    "page": 1,
                    "confidence": 0.97,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 110, "y1": 20},
                    "is_pii": True,
                    "requires_verification": True,
                    "verification_reason": "Identity claim",
                    "extraction_method": "native_text",
                },
                {
                    "candidate_id": "cand-roll",
                    "label": "registration_number",
                    "category": "registration_number",
                    "raw_value": "RC2026001",
                    "normalized_value": "RC2026001",
                    "source_text": "Roll Number: RC2026001",
                    "page": 1,
                    "confidence": 0.95,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 70, "x1": 120, "y1": 80},
                    "is_pii": False,
                    "requires_verification": True,
                    "verification_reason": "Academic identifier",
                    "extraction_method": "native_text",
                },
                {
                    "candidate_id": "cand-score",
                    "label": "score",
                    "category": "score",
                    "raw_value": "A+",
                    "normalized_value": "A+",
                    "source_text": "Grade: A+",
                    "page": 1,
                    "confidence": 0.92,
                    "bounding_box": {"page": 1, "x0": 10, "y0": 90, "x1": 60, "y1": 100},
                    "is_pii": False,
                    "requires_verification": True,
                    "verification_reason": "Academic score",
                    "extraction_method": "native_text",
                },
            ],
            "generalized_analysis": {
                "document_profile_payload": {
                    "document_family_hints": ["report_card"],
                },
                "verification_summary_payload": {
                    "document_type": "report_card",
                },
            },
            "warnings": [{"code": "TEST_WARNING", "message": "synthetic"}],
            "metadata": {"page_count": 1, "extraction_method": "native_text"},
            "safety_report": {"sandboxed": True, "malware_scan_passed": True},
            "evidence_lines": [{"page": 1, "text": "Student Name: Riya Sen"}],
            "error_message": None,
        }

        with patch("backend.app.workflow.runtime._load_extraction_result", return_value=raw_result):
            payload = extract_document_payload(Path("synthetic.pdf"))

        view = payload["view"]
        self.assertEqual(view["document_type"], "report_card")
        self.assertNotIn("institution", view["fields"])
        self.assertNotIn("credential", view["fields"])
        self.assertNotIn("id", view["fields"])
        self.assertIn("name", view["fields"])
        self.assertIn("registration-number", view["fields"])
        self.assertIn("score", view["fields"])
        self.assertEqual(
            [detail["label"] for detail in view["field_details"]],
            ["name", "registration_number", "score"],
        )
        self.assertEqual(view["warnings"][0]["code"], "TEST_WARNING")
        self.assertEqual(view["metadata"]["extraction_method"], "native_text")
        self.assertEqual(payload["trust_input"]["fields"][0]["name"], "name")
        self.assertEqual(payload["connector_input"]["name"], "Riya Sen")
        self.assertEqual(payload["connector_input"]["institution"], "Demo Central School")
        self.assertEqual(payload["connector_input"]["document_id"], "RC2026001")


class NvidiaPiiEnrichmentTests(unittest.TestCase):
    def test_gliner_enrichment_refines_candidate_typing_without_replacing_geometry(self):
        base_candidate = FieldCandidate(
            candidate_id="cand-aadhaar",
            label="document_id",
            category="document_number",
            raw_value="1234 5678 9012",
            normalized_value="123456789012",
            source_text="Aadhaar Number: 1234 5678 9012",
            evidence_snippet="Aadhaar Number: 1234 5678 9012",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=120, y1=20),
            confidence=0.91,
            is_pii=False,
            requires_verification=True,
            verification_reason="Identifier claim",
            extraction_method="native_text",
        )
        evidence_lines = [
            EvidenceLine(
                page=1,
                text="Aadhaar Number: 1234 5678 9012",
                bbox=BoundingBox(page=1, x0=10, y0=10, x1=120, y1=20),
                token_indices=[0, 1],
            )
        ]
        spatial_text_map = [
            SpatialTextToken(text="Aadhaar Number:", bbox=[10, 10, 60, 20], page=1),
            SpatialTextToken(text="1234 5678 9012", bbox=[62, 10, 120, 20], page=1),
        ]

        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "demo-key",
                "NVIDIA_GLINER_PREPROCESSING_ENABLED": "1",
            },
            clear=False,
        ), patch(
            "extraction.analysis.nvidia_enrichment.NvidiaChatClient.chat_json",
            return_value={
                "entities": [
                    {
                        "text": "1234 5678 9012",
                        "label": "AADHAAR_NUMBER",
                        "confidence": 0.94,
                    }
                ]
            },
        ):
            merged, metadata = enrich_field_candidates_with_nvidia(
                raw_text="Aadhaar Number: 1234 5678 9012",
                evidence_lines=evidence_lines,
                spatial_text_map=spatial_text_map,
                extraction_method="native_text",
                warnings=[],
                base_candidates=[base_candidate],
            )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].category, "national_identifier")
        self.assertEqual(merged[0].bounding_box.x0, 10)
        self.assertTrue(metadata.pii_enrichment_used)
        self.assertEqual(metadata.pii_model_used, "nvidia/gliner-pii")

    def test_gliner_failure_keeps_deterministic_candidates(self):
        base_candidate = FieldCandidate(
            candidate_id="cand-name",
            label="name",
            category="person_name",
            raw_value="Asha Rao",
            normalized_value="Asha Rao",
            source_text="Holder Name: Asha Rao",
            evidence_snippet="Holder Name: Asha Rao",
            page=1,
            bounding_box=BoundingBox(page=1, x0=10, y0=10, x1=90, y1=20),
            confidence=0.95,
            is_pii=True,
            requires_verification=True,
            verification_reason="Identity claim",
            extraction_method="native_text",
        )
        warnings: list[ExtractionWarning] = []
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "demo-key",
                "NVIDIA_GLINER_PREPROCESSING_ENABLED": "1",
            },
            clear=False,
        ), patch(
            "extraction.analysis.nvidia_enrichment.NvidiaChatClient.chat_json",
            side_effect=NvidiaInferenceError("network_error", "request failed"),
        ):
            merged, metadata = enrich_field_candidates_with_nvidia(
                raw_text="Holder Name: Asha Rao",
                evidence_lines=[
                    EvidenceLine(
                        page=1,
                        text="Holder Name: Asha Rao",
                        bbox=BoundingBox(page=1, x0=10, y0=10, x1=90, y1=20),
                    )
                ],
                spatial_text_map=[SpatialTextToken(text="Asha Rao", bbox=[40, 10, 90, 20], page=1)],
                extraction_method="native_text",
                warnings=warnings,
                base_candidates=[base_candidate],
            )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].category, "person_name")
        self.assertTrue(metadata.fallback_used)
        self.assertIn("NVIDIA_PII_ENRICHMENT_FAILED", metadata.warning_codes)
        self.assertEqual(warnings[0].code, "NVIDIA_PII_ENRICHMENT_FAILED")


def _write_text_pdf(path: Path, lines: list[str]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 20
    document.save(str(path))
    document.close()


if __name__ == "__main__":
    unittest.main()
