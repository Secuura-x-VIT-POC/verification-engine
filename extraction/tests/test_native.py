from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from extraction import run_extraction


class NativeExtractionTests(unittest.TestCase):
    def test_text_pdf_produces_grounded_phase3_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "degree.pdf"
            _write_pdf(
                pdf_path,
                [
                    "Student Name: Riya Sen",
                    "Institution: VIT University",
                    "Registration Number: 21CSE001",
                    "CGPA: 8.75",
                ],
            )
            processing_result, workspace_view = run_extraction("test-native-001", str(pdf_path))

        self.assertGreaterEqual(len(processing_result.field_candidates), 4)
        self.assertTrue(any(candidate.bounding_boxes for candidate in processing_result.field_candidates))
        self.assertTrue(all(candidate.detected_by for candidate in processing_result.field_candidates))
        self.assertTrue(0.0 <= processing_result.extraction_quality <= 1.0)
        self.assertEqual(workspace_view.extraction_quality, processing_result.extraction_quality)

    def test_resume_like_pdf_avoids_header_and_skill_false_positives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "resume.pdf"
            _write_pdf(
                pdf_path,
                [
                    "SHIVAM AHER",
                    "9823591095 shivamaher101@gmail.com LinkedIn",
                    "SUMMARY",
                    "IT student seeking internship opportunities",
                    "TECHNICAL COMPETENCIES",
                    "Languages: Python, C, Java",
                    "Web Technologies: HTML, CSS, JavaScript",
                    "EDUCATION",
                    "B.R.A.C.T.'s Vishwakarma Institute of Technology",
                    "CGPA - 9.07/10",
                    "EXTRACURRICULAR ACTIVITIES",
                ],
            )
            processing_result, _ = run_extraction("test-native-resume-001", str(pdf_path))

        labels_to_values = {(candidate.label, candidate.raw_value) for candidate in processing_result.field_candidates}
        self.assertEqual(processing_result.document_type_hint, "resume")
        self.assertNotIn(("Identifier", "SUMMARY"), labels_to_values)
        self.assertNotIn(("Identifier", "TECHNICAL"), labels_to_values)
        self.assertNotIn(("Identifier", "EDUCATION"), labels_to_values)
        self.assertFalse(any(candidate.category == "identifier" and candidate.raw_value == "Python, C, Java" for candidate in processing_result.field_candidates))
        self.assertFalse(any(candidate.category == "personal_name" and candidate.raw_value == "Python" for candidate in processing_result.field_candidates))


def _write_pdf(path: Path, lines: list[str]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 22
    document.save(str(path))
    document.close()
