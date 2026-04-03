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
from extraction.analysis.pipeline import build_evidence_lines, build_generalized_analysis, extract_field_candidates
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
        self.assertIsNotNone(result.ocr_metadata)
        self.assertEqual(result.ocr_metadata.engine_used, "native_text")
        self.assertFalse(result.ocr_metadata.ocr_applied)
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
            "ocr_metadata": {
                "backend_mode": "AUTO",
                "engine_used": "native_text",
                "engines_used": ["native_text"],
                "native_text_used": True,
                "ocr_applied": False,
                "fallback_used": False,
                "average_confidence": 1.0,
                "preprocessing_applied": [],
                "pages_ocrd": [],
                "page_metadata": [],
                "warning_codes": [],
            },
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
        self.assertEqual(view["ocr_metadata"]["engine_used"], "native_text")
        self.assertEqual(payload["trust_input"]["fields"][0]["name"], "name")
        self.assertEqual(payload["connector_input"]["name"], "Riya Sen")
        self.assertEqual(payload["connector_input"]["institution"], "Demo Central School")
        self.assertEqual(payload["connector_input"]["document_id"], "RC2026001")


class ExtractionProvenanceTests(unittest.TestCase):
    def test_same_line_binding_prefers_value_span_and_tight_bbox(self):
        spatial_text_map = [
            SpatialTextToken(text="DOB:", bbox=[10, 10, 40, 20], page=1),
            SpatialTextToken(text="09/03/2006", bbox=[45, 10, 105, 20], page=1),
        ]
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text="DOB: 09/03/2006",
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        dob = next(candidate for candidate in candidates if candidate.category == "date_of_birth")
        self.assertEqual(dob.source_text, "09/03/2006")
        self.assertEqual(dob.evidence_snippet, "dob: 09/03/2006".title().replace("Dob", "DOB"))
        self.assertEqual(dob.page, 1)
        self.assertEqual(dob.bounding_box.x0, 45)
        self.assertEqual(dob.context_bounding_box.x0, 10)
        self.assertEqual(dob.provenance_method, "same_line")
        self.assertEqual(dob.source_engine, "native_text")
        self.assertGreater(dob.confidence, 0.9)

    def test_nearby_below_binding_uses_value_line_box(self):
        spatial_text_map = [
            SpatialTextToken(text="Date", bbox=[10, 10, 35, 20], page=1),
            SpatialTextToken(text="of", bbox=[38, 10, 48, 20], page=1),
            SpatialTextToken(text="Birth", bbox=[51, 10, 80, 20], page=1),
            SpatialTextToken(text="09/03/2006", bbox=[10, 28, 70, 38], page=1),
        ]
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text="Date of Birth\n09/03/2006",
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        dob = next(candidate for candidate in candidates if candidate.category == "date_of_birth")
        self.assertEqual(dob.source_text, "09/03/2006")
        self.assertEqual(dob.bounding_box.y0, 28)
        self.assertEqual(dob.context_bounding_box.y0, 10)
        self.assertEqual(dob.provenance_method, "nearby_below")
        self.assertLess(dob.confidence, 0.9)

    def test_value_span_evidence_is_preferred_over_header_text(self):
        spatial_text_map = [
            SpatialTextToken(text="Government", bbox=[10, 10, 55, 20], page=1),
            SpatialTextToken(text="of", bbox=[58, 10, 68, 20], page=1),
            SpatialTextToken(text="India", bbox=[71, 10, 95, 20], page=1),
            SpatialTextToken(text="Aadhaar", bbox=[10, 28, 50, 38], page=1),
            SpatialTextToken(text="Number:", bbox=[53, 28, 95, 38], page=1),
            SpatialTextToken(text="1234", bbox=[98, 28, 120, 38], page=1),
            SpatialTextToken(text="5678", bbox=[123, 28, 145, 38], page=1),
            SpatialTextToken(text="9012", bbox=[148, 28, 170, 38], page=1),
        ]
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text="Government of India\nAadhaar Number: 1234 5678 9012",
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        aadhaar = next(candidate for candidate in candidates if candidate.category == "national_identifier")
        self.assertEqual(aadhaar.source_text, "1234 5678 9012")
        self.assertNotEqual(aadhaar.source_text, "Government of India")
        self.assertIn("Aadhaar Number", aadhaar.evidence_snippet)
        self.assertEqual(aadhaar.bounding_box.x0, 98)

    def test_identifier_and_date_context_is_disambiguated_locally(self):
        spatial_text_map = [
            SpatialTextToken(text="Government", bbox=[10, 10, 55, 20], page=1),
            SpatialTextToken(text="of", bbox=[58, 10, 68, 20], page=1),
            SpatialTextToken(text="India", bbox=[71, 10, 95, 20], page=1),
            SpatialTextToken(text="DOB", bbox=[10, 28, 28, 38], page=1),
            SpatialTextToken(text=":", bbox=[30, 28, 34, 38], page=1),
            SpatialTextToken(text="09/03/2006", bbox=[38, 28, 98, 38], page=1),
            SpatialTextToken(text="PAN", bbox=[10, 46, 28, 56], page=1),
            SpatialTextToken(text=":", bbox=[30, 46, 34, 56], page=1),
            SpatialTextToken(text="ABCDE1234F", bbox=[38, 46, 96, 56], page=1),
            SpatialTextToken(text="Issue", bbox=[10, 64, 35, 74], page=1),
            SpatialTextToken(text="Date:", bbox=[38, 64, 66, 74], page=1),
            SpatialTextToken(text="2024-05-01", bbox=[70, 64, 130, 74], page=1),
        ]
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text="Government of India\nDOB: 09/03/2006\nPAN: ABCDE1234F\nIssue Date: 2024-05-01",
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        categories = {candidate.category: candidate for candidate in candidates}
        self.assertEqual(categories["date_of_birth"].source_text, "09/03/2006")
        self.assertEqual(categories["tax_identifier"].source_text, "ABCDE1234F")
        self.assertEqual(categories["issue_date"].source_text, "2024-05-01")

    def test_page_and_source_engine_are_preserved_for_ocr_candidates(self):
        spatial_text_map = [
            SpatialTextToken(text="Date", bbox=[10, 10, 35, 20], page=1),
            SpatialTextToken(text="of", bbox=[38, 10, 48, 20], page=1),
            SpatialTextToken(text="Birth", bbox=[51, 10, 80, 20], page=1),
            SpatialTextToken(text="09/03/2006", bbox=[85, 10, 145, 20], page=1, source="ocr_paddleocr", confidence=0.82),
            SpatialTextToken(text="Roll", bbox=[10, 10, 30, 20], page=2, source="ocr_tesseract", confidence=0.77),
            SpatialTextToken(text="No:", bbox=[34, 10, 52, 20], page=2, source="ocr_tesseract", confidence=0.77),
            SpatialTextToken(text="RC2026001", bbox=[56, 10, 110, 20], page=2, source="ocr_tesseract", confidence=0.77),
        ]
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text="Date of Birth 09/03/2006\nRoll No: RC2026001",
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="hybrid",
            warnings=[],
        )

        roll = next(candidate for candidate in candidates if candidate.category == "registration_number")
        self.assertEqual(roll.page, 2)
        self.assertEqual(roll.source_engine, "ocr_tesseract")
        self.assertEqual(roll.bounding_box.page, 2)

    def test_weak_pattern_only_provenance_gets_lower_confidence(self):
        spatial_text_map = [
            SpatialTextToken(text="DOB:", bbox=[10, 10, 40, 20], page=1),
            SpatialTextToken(text="09/03/2006", bbox=[45, 10, 105, 20], page=1),
            SpatialTextToken(text="Ref", bbox=[10, 28, 25, 38], page=1),
            SpatialTextToken(text="2024-05-01", bbox=[30, 28, 90, 38], page=1),
        ]
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text="DOB: 09/03/2006\nRef 2024-05-01",
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        dob = next(candidate for candidate in candidates if candidate.category == "date_of_birth")
        generic_date = next(candidate for candidate in candidates if candidate.category == "date_reference")
        self.assertGreater(dob.confidence, generic_date.confidence)


class ExtractionSemanticNormalizationTests(unittest.TestCase):
    def test_aadhaar_like_document_emits_specific_semantic_labels(self):
        spatial_text_map = [
            SpatialTextToken(text="Government", bbox=[10, 10, 55, 20], page=1),
            SpatialTextToken(text="of", bbox=[58, 10, 68, 20], page=1),
            SpatialTextToken(text="India", bbox=[71, 10, 95, 20], page=1),
            SpatialTextToken(text="Holder", bbox=[10, 28, 42, 38], page=1),
            SpatialTextToken(text="Name:", bbox=[46, 28, 78, 38], page=1),
            SpatialTextToken(text="Asha", bbox=[82, 28, 105, 38], page=1),
            SpatialTextToken(text="Rao", bbox=[108, 28, 130, 38], page=1),
            SpatialTextToken(text="DOB:", bbox=[10, 46, 35, 56], page=1),
            SpatialTextToken(text="09/03/2006", bbox=[39, 46, 99, 56], page=1),
            SpatialTextToken(text="Aadhaar", bbox=[10, 64, 50, 74], page=1),
            SpatialTextToken(text="Number:", bbox=[54, 64, 96, 74], page=1),
            SpatialTextToken(text="1234", bbox=[100, 64, 122, 74], page=1),
            SpatialTextToken(text="5678", bbox=[125, 64, 147, 74], page=1),
            SpatialTextToken(text="9012", bbox=[150, 64, 172, 74], page=1),
        ]
        raw_text = "Government of India\nHolder Name: Asha Rao\nDOB: 09/03/2006\nAadhaar Number: 1234 5678 9012"
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text=raw_text,
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )
        _, _, payload, _ = build_generalized_analysis(
            raw_text=raw_text,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        labels = {candidate.label for candidate in candidates}
        self.assertIn("full_name", labels)
        self.assertIn("date_of_birth", labels)
        self.assertIn("aadhaar_number", labels)
        self.assertNotIn("government_identifier", labels)
        self.assertIn("aadhaar_card", payload.document_profile_payload.document_family_hints)

    def test_pan_like_document_prefers_pan_number_and_dob_over_generic_fields(self):
        spatial_text_map = [
            SpatialTextToken(text="INCOME", bbox=[10, 10, 40, 20], page=1),
            SpatialTextToken(text="TAX", bbox=[44, 10, 62, 20], page=1),
            SpatialTextToken(text="DEPARTMENT", bbox=[66, 10, 122, 20], page=1),
            SpatialTextToken(text="Full", bbox=[10, 28, 30, 38], page=1),
            SpatialTextToken(text="Name:", bbox=[34, 28, 62, 38], page=1),
            SpatialTextToken(text="Asha", bbox=[66, 28, 89, 38], page=1),
            SpatialTextToken(text="Rao", bbox=[92, 28, 114, 38], page=1),
            SpatialTextToken(text="PAN:", bbox=[10, 46, 32, 56], page=1),
            SpatialTextToken(text="ABCDE1234F", bbox=[36, 46, 96, 56], page=1),
            SpatialTextToken(text="Date", bbox=[10, 64, 34, 74], page=1),
            SpatialTextToken(text="of", bbox=[38, 64, 48, 74], page=1),
            SpatialTextToken(text="Birth:", bbox=[52, 64, 82, 74], page=1),
            SpatialTextToken(text="2001-02-01", bbox=[86, 64, 146, 74], page=1),
        ]
        raw_text = "INCOME TAX DEPARTMENT\nFull Name: Asha Rao\nPAN: ABCDE1234F\nDate of Birth: 2001-02-01"
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text=raw_text,
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )
        labels = {candidate.label for candidate in candidates}

        self.assertIn("full_name", labels)
        self.assertIn("pan_number", labels)
        self.assertIn("date_of_birth", labels)
        self.assertNotIn("document_id", labels)
        self.assertNotIn("government_identifier", labels)

    def test_report_card_document_emits_student_and_academic_semantics(self):
        spatial_text_map = [
            SpatialTextToken(text="Student", bbox=[10, 10, 42, 20], page=1),
            SpatialTextToken(text="Name:", bbox=[46, 10, 74, 20], page=1),
            SpatialTextToken(text="Riya", bbox=[78, 10, 100, 20], page=1),
            SpatialTextToken(text="Sen", bbox=[103, 10, 122, 20], page=1),
            SpatialTextToken(text="Roll", bbox=[10, 28, 30, 38], page=1),
            SpatialTextToken(text="No:", bbox=[34, 28, 52, 38], page=1),
            SpatialTextToken(text="RC2026001", bbox=[56, 28, 112, 38], page=1),
            SpatialTextToken(text="Board", bbox=[10, 46, 36, 56], page=1),
            SpatialTextToken(text="Name:", bbox=[40, 46, 68, 56], page=1),
            SpatialTextToken(text="CBSE", bbox=[72, 46, 100, 56], page=1),
            SpatialTextToken(text="School", bbox=[10, 64, 38, 74], page=1),
            SpatialTextToken(text="Name:", bbox=[42, 64, 70, 74], page=1),
            SpatialTextToken(text="Demo", bbox=[74, 64, 102, 74], page=1),
            SpatialTextToken(text="Central", bbox=[105, 64, 142, 74], page=1),
            SpatialTextToken(text="School", bbox=[145, 64, 174, 74], page=1),
            SpatialTextToken(text="Exam", bbox=[10, 82, 34, 92], page=1),
            SpatialTextToken(text="Year:", bbox=[38, 82, 64, 92], page=1),
            SpatialTextToken(text="2024", bbox=[68, 82, 92, 92], page=1),
            SpatialTextToken(text="Grade:", bbox=[10, 100, 42, 110], page=1),
            SpatialTextToken(text="A+", bbox=[46, 100, 58, 110], page=1),
            SpatialTextToken(text="Result:", bbox=[10, 118, 46, 128], page=1),
            SpatialTextToken(text="PASS", bbox=[50, 118, 76, 128], page=1),
        ]
        raw_text = (
            "Student Name: Riya Sen\nRoll No: RC2026001\nBoard Name: CBSE\n"
            "School Name: Demo Central School\nExam Year: 2024\nGrade: A+\nResult: PASS"
        )
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text=raw_text,
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        labels = {candidate.label for candidate in candidates}
        self.assertIn("student_name", labels)
        self.assertIn("roll_number", labels)
        self.assertIn("board_name", labels)
        self.assertIn("institution_name", labels)
        self.assertIn("exam_year", labels)
        self.assertIn("grade", labels)
        self.assertIn("result_status", labels)
        self.assertNotIn("date", labels)
        self.assertNotIn("document_id", labels)

    def test_generic_labels_remain_when_context_is_truly_ambiguous(self):
        spatial_text_map = [
            SpatialTextToken(text="Reference", bbox=[10, 10, 52, 20], page=1),
            SpatialTextToken(text="ID", bbox=[56, 10, 66, 20], page=1),
            SpatialTextToken(text="ZXQ1234567", bbox=[70, 10, 132, 20], page=1),
            SpatialTextToken(text="Date", bbox=[10, 28, 32, 38], page=1),
            SpatialTextToken(text="2024-05-01", bbox=[36, 28, 96, 38], page=1),
        ]
        raw_text = "Reference ID ZXQ1234567\nDate 2024-05-01"
        evidence_lines = build_evidence_lines(spatial_text_map)

        candidates = extract_field_candidates(
            raw_text=raw_text,
            evidence_lines=evidence_lines,
            spatial_text_map=spatial_text_map,
            extraction_method="native_text",
            warnings=[],
        )

        labels = {candidate.label for candidate in candidates}
        self.assertIn("document_number", labels)
        self.assertIn("date", labels)


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

    def test_gliner_does_not_override_stronger_deterministic_family_aware_labels(self):
        base_candidate = FieldCandidate(
            candidate_id="cand-aadhaar",
            label="aadhaar_number",
            category="national_identifier",
            raw_value="1234 5678 9012",
            normalized_value="123456789012",
            source_text="Aadhaar Number: 1234 5678 9012",
            evidence_snippet="Aadhaar Number: 1234 5678 9012",
            page=1,
            bounding_box=BoundingBox(page=1, x0=62, y0=10, x1=120, y1=20),
            confidence=0.96,
            is_pii=True,
            requires_verification=True,
            verification_reason="Identity claim",
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
                        "label": "DOCUMENT_NUMBER",
                        "confidence": 0.93,
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
        self.assertEqual(merged[0].label, "aadhaar_number")
        self.assertEqual(merged[0].category, "national_identifier")
        self.assertTrue(metadata.pii_enrichment_used)


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
