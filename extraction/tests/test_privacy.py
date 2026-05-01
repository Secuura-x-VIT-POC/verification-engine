from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from extraction import run_extraction, run_extraction_with_feedback
from extraction.models import VerificationStatus


class PrivacyTests(unittest.TestCase):
    def test_workspace_masks_pii_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "identity.pdf"
            _write_pdf(
                pdf_path,
                [
                    "Holder Name: Asha Rao",
                    "Registration Number: 21CSE001",
                ],
            )
            processing_result, workspace_view = run_extraction("test-privacy-001", str(pdf_path))

        originals = {candidate.field_id: candidate.raw_value for candidate in processing_result.field_candidates}
        for field_view in workspace_view.field_views:
            if field_view.is_pii:
                self.assertNotEqual(field_view.value_preview, originals.get(field_view.field_id))
        self.assertFalse(workspace_view.raw_text_persisted)
        self.assertFalse(workspace_view.pii_persisted)

    def test_feedback_marks_target_field_red(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "identity.pdf"
            _write_pdf(pdf_path, ["Holder Name: Asha Rao"])
            processing_result, _ = run_extraction("test-privacy-002", str(pdf_path))
            target_id = processing_result.field_candidates[0].field_id
            updated_result, _ = run_extraction_with_feedback(
                "test-privacy-002",
                str(pdf_path),
                verifier_mismatches=[target_id],
            )

        updated = next(candidate for candidate in updated_result.field_candidates if candidate.field_id == target_id)
        self.assertEqual(updated.verification_status, VerificationStatus.RED)


def _write_pdf(path: Path, lines: list[str]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 22
    document.save(str(path))
    document.close()
