import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extraction.ocr.engine import (
    OCRBackendUnavailable,
    OCRRuntimeConfig,
    _extract_ocr_page_with_best_engine,
    extract_native,
    load_ocr_runtime_config,
)
from extraction.parser.document_parser import extract_document_data_with_strategy
from extraction.schema.models import SafetyReport


class OCRBackendConfigTests(unittest.TestCase):
    def test_load_ocr_runtime_config_defaults_to_auto(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_ocr_runtime_config()

        self.assertEqual(config.backend_mode, "AUTO")
        self.assertEqual(config.dpi, 300)
        self.assertTrue(config.preprocessing_enabled)

    def test_load_ocr_runtime_config_honors_env(self):
        with patch.dict(
            os.environ,
            {
                "OCR_BACKEND_MODE": "TESSERACT_ONLY",
                "OCR_DPI": "240",
                "OCR_PREPROCESSING_ENABLED": "0",
                "PADDLEOCR_ENABLED": "0",
            },
            clear=True,
        ):
            config = load_ocr_runtime_config()

        self.assertEqual(config.backend_mode, "TESSERACT_ONLY")
        self.assertEqual(config.dpi, 240)
        self.assertFalse(config.preprocessing_enabled)
        self.assertFalse(config.paddle_enabled)


class OCRBackendSelectionTests(unittest.TestCase):
    def test_best_engine_falls_back_to_tesseract_when_paddle_is_unavailable(self):
        fake_page = MagicMock()
        fake_page.number = 0
        config = OCRRuntimeConfig(backend_mode="AUTO")

        tesseract_payload = {
            "page": 1,
            "tokens": [{"text": "1234", "bbox": [1, 2, 3, 4], "page": 1, "source": "ocr_tesseract", "confidence": 0.9}],
            "text": "1234",
            "char_count": 4,
            "character_density": 11.0,
            "average_confidence": 0.9,
            "engine": "tesseract",
            "fallback_used": False,
            "preprocessing_applied": ["grayscale"],
            "warning_codes": [],
            "page_metadata": {
                "page": 1,
                "engine": "tesseract",
                "used_native_text": False,
                "average_confidence": 0.9,
                "preprocessing_applied": ["grayscale"],
                "warning_codes": [],
            },
            "page_stats": {
                "page": 1,
                "word_count": 1,
                "character_density": 11.0,
                "extraction_method": "ocr",
                "ocr_engine": "tesseract",
            },
        }

        with patch(
            "extraction.ocr.engine._extract_ocr_page_with_paddleocr",
            side_effect=OCRBackendUnavailable("PaddleOCR unavailable"),
        ), patch(
            "extraction.ocr.engine._extract_ocr_page_with_tesseract",
            return_value=tesseract_payload,
        ):
            page_payload = _extract_ocr_page_with_best_engine(fake_page, 1, config)

        self.assertEqual(page_payload["engine"], "tesseract")
        self.assertTrue(page_payload["fallback_used"])
        self.assertIn("PADDLEOCR_UNAVAILABLE", page_payload["warning_codes"])


class OCRMetadataTests(unittest.TestCase):
    def test_extract_native_emits_ocr_metadata_without_using_ocr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "native.pdf"
            _write_text_pdf(file_path, ["Name: Asha Rao", "PAN: ABCDE1234F"])

            payload = extract_native(file_path)

        self.assertEqual(payload["ocr_metadata"]["engine_used"], "native_text")
        self.assertFalse(payload["ocr_metadata"]["ocr_applied"])
        self.assertTrue(payload["ocr_metadata"]["native_text_used"])


class OCRParserIntegrationTests(unittest.TestCase):
    def test_auto_strategy_uses_pp_chatocr_metadata_for_scanned_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "scan.pdf"
            _write_text_pdf(file_path, ["placeholder"])

            pp_payload = {
                "extraction_method": "pp_chatocr_v4",
                "ocr_performed": True,
                "advanced_ocr_performed": True,
                "page_count": 1,
                "field_count": 2,
                "warnings": [],
                "ocr_metadata": {
                    "method_used": "pp_chatocr_v4",
                    "engine_used": "pp_chatocr_v4",
                    "engines_used": ["pp_chatocr_v4"],
                    "native_text_used": False,
                    "ocr_applied": True,
                    "fallback_used": False,
                    "fallback_triggered": False,
                    "average_confidence": 0.945,
                    "avg_confidence": 0.945,
                    "total_pages": 1,
                    "ocr_pages": [1],
                    "pages_ocrd": [1],
                    "warning_codes": [],
                },
                "spatial_text_map": [
                    {
                        "text_preview": "Asha Rao",
                        "bbox": [10, 10, 60, 20],
                        "polygon": [[10, 10], [60, 10], [60, 20], [10, 20]],
                        "page_number": 1,
                        "source": "pp_chatocr_v4",
                        "confidence": 0.96,
                    },
                ],
                "field_candidates": [
                    {
                        "field_id": "holder_name",
                        "label": "Holder Name",
                        "extracted_value": "Asha Rao",
                        "normalized_value": "Asha Rao",
                        "category": "personal_name",
                        "confidence": 0.96,
                        "page": 1,
                        "page_number": 1,
                        "bbox": [10, 10, 60, 20],
                        "polygon": [[10, 10], [60, 10], [60, 20], [10, 20]],
                        "coordinate_space": "pp_chatocr_image_pixels",
                        "extraction_method": "pp_chatocr_v4",
                        "requires_verification": True,
                        "bounding_box": {"page": 1, "page_number": 1, "x0": 10, "y0": 10, "x1": 60, "y1": 20, "bbox": [10, 10, 60, 20], "coordinate_space": "pp_chatocr_image_pixels"},
                        "bounding_boxes": [{"page": 1, "page_number": 1, "x0": 10, "y0": 10, "x1": 60, "y1": 20, "bbox": [10, 10, 60, 20], "coordinate_space": "pp_chatocr_image_pixels"}],
                    },
                    {
                        "field_id": "aadhaar_number",
                        "label": "Aadhaar Number",
                        "extracted_value": "1234 5678 9012",
                        "normalized_value": "1234 5678 9012",
                        "category": "identifier",
                        "confidence": 0.93,
                        "page": 1,
                        "page_number": 1,
                        "bbox": [76, 30, 148, 40],
                        "polygon": [[76, 30], [148, 30], [148, 40], [76, 40]],
                        "coordinate_space": "pp_chatocr_image_pixels",
                        "extraction_method": "pp_chatocr_v4",
                        "requires_verification": True,
                        "bounding_box": {"page": 1, "page_number": 1, "x0": 76, "y0": 30, "x1": 148, "y1": 40, "bbox": [76, 30, 148, 40], "coordinate_space": "pp_chatocr_image_pixels"},
                        "bounding_boxes": [{"page": 1, "page_number": 1, "x0": 76, "y0": 30, "x1": 148, "y1": 40, "bbox": [76, 30, 148, 40], "coordinate_space": "pp_chatocr_image_pixels"}],
                    },
                ],
                "evidence_lines": [{"text_preview": "Holder Name Asha Rao", "page_number": 1, "bbox": [10, 10, 60, 20]}],
                "layout_blocks": [],
                "table_cells": [],
                "engine_metadata": {"source": "pp_chatocr_v4"},
            }

            with patch(
                "extraction.pipeline.run_pp_chatocr_v4_extraction",
                return_value=pp_payload,
            ):
                result = extract_document_data_with_strategy(str(file_path), strategy="auto")

        self.assertTrue(result.is_successful)
        self.assertTrue(result.used_ocr)
        self.assertIsNotNone(result.ocr_metadata)
        self.assertEqual(result.ocr_metadata.engine_used, "pp_chatocr_v4")
        self.assertEqual(result.spatial_text_map[0].polygon[0], [10.0, 10.0])
        self.assertTrue(any(candidate.category == "personal_name" for candidate in result.field_candidates))
        self.assertTrue(any(candidate.category == "identifier" for candidate in result.field_candidates))
        self.assertEqual(result.metadata.extraction_method, "pp_chatocr_v4")


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
