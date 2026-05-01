from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from extraction import run_extraction


class GroundingTests(unittest.TestCase):
    def test_grounded_fields_include_pdf_space_boxes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "identity.pdf"
            _write_pdf(
                pdf_path,
                [
                    "Holder Name: Asha Rao",
                    "Aadhaar Number: 1234 5678 9012",
                    "Date of Birth: 01/02/2001",
                ],
            )
            processing_result, _ = run_extraction("test-grounding-001", str(pdf_path))

        grounded = [candidate for candidate in processing_result.field_candidates if candidate.bounding_boxes]
        self.assertTrue(grounded)
        for candidate in grounded:
            box = candidate.bounding_boxes[0]
            self.assertGreaterEqual(box.x1, box.x0)
            self.assertGreaterEqual(box.y1, box.y0)
            self.assertLessEqual(len(candidate.source_text or ""), 120)


def _write_pdf(path: Path, lines: list[str]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 22
    document.save(str(path))
    document.close()
