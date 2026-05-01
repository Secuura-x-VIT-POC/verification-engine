from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from extraction import run_extraction
from extraction.models import Sensitivity


class PIITests(unittest.TestCase):
    def test_name_and_identifier_fields_are_flagged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "identity.pdf"
            _write_pdf(
                pdf_path,
                [
                    "Holder Name: Asha Rao",
                    "PAN Number: ABCDE1234F",
                ],
            )
            processing_result, _ = run_extraction("test-pii-001", str(pdf_path))

        name_fields = [candidate for candidate in processing_result.field_candidates if candidate.category == "personal_name"]
        id_fields = [candidate for candidate in processing_result.field_candidates if candidate.category == "identifier"]
        self.assertTrue(name_fields)
        self.assertTrue(id_fields)
        self.assertTrue(all(candidate.is_pii for candidate in name_fields + id_fields))
        self.assertTrue(all(candidate.sensitivity == Sensitivity.HIGH for candidate in name_fields + id_fields))


def _write_pdf(path: Path, lines: list[str]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 22
    document.save(str(path))
    document.close()
