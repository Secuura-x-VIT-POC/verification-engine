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
    def test_auto_strategy_uses_paddle_metadata_for_scanned_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "scan.pdf"
            _write_text_pdf(file_path, ["placeholder"])

            native_result = {
                "raw_text": "",
                "spatial_text_map": [],
                "page_count": 1,
                "word_count": 0,
                "character_density": 0.0,
                "page_stats": [
                    {"page": 1, "word_count": 0, "character_density": 0.0, "extraction_method": "native_text", "ocr_engine": "native_text"}
                ],
                "ocr_metadata": {
                    "backend_mode": "AUTO",
                    "engine_used": "native_text",
                    "engines_used": ["native_text"],
                    "native_text_used": True,
                    "ocr_applied": False,
                    "fallback_used": False,
                    "average_confidence": None,
                    "preprocessing_applied": [],
                    "pages_ocrd": [],
                    "page_metadata": [],
                    "warning_codes": [],
                },
            }
            hybrid_result = {
                "raw_text": "Holder Name: Asha Rao\nAadhaar Number: 1234 5678 9012",
                "spatial_text_map": [
                    {
                        "text": "Holder Name:",
                        "bbox": [10, 10, 60, 20],
                        "polygon": [[10, 10], [60, 10], [60, 20], [10, 20]],
                        "page": 1,
                        "source": "ocr_paddleocr",
                        "confidence": 0.95,
                    },
                    {
                        "text": "Asha Rao",
                        "bbox": [62, 10, 110, 20],
                        "polygon": [[62, 10], [110, 10], [110, 20], [62, 20]],
                        "page": 1,
                        "source": "ocr_paddleocr",
                        "confidence": 0.96,
                    },
                    {
                        "text": "Aadhaar Number:",
                        "bbox": [10, 30, 74, 40],
                        "polygon": [[10, 30], [74, 30], [74, 40], [10, 40]],
                        "page": 1,
                        "source": "ocr_paddleocr",
                        "confidence": 0.94,
                    },
                    {
                        "text": "1234 5678 9012",
                        "bbox": [76, 30, 148, 40],
                        "polygon": [[76, 30], [148, 30], [148, 40], [76, 40]],
                        "page": 1,
                        "source": "ocr_paddleocr",
                        "confidence": 0.93,
                    },
                ],
                "page_count": 1,
                "word_count": 4,
                "character_density": 12.0,
                "page_stats": [
                    {"page": 1, "word_count": 4, "character_density": 12.0, "extraction_method": "ocr", "ocr_engine": "paddleocr"}
                ],
                "ocr_metadata": {
                    "backend_mode": "AUTO",
                    "engine_used": "paddleocr",
                    "engines_used": ["paddleocr"],
                    "native_text_used": False,
                    "ocr_applied": True,
                    "fallback_used": False,
                    "average_confidence": 0.945,
                    "preprocessing_applied": ["grayscale", "autocontrast"],
                    "pages_ocrd": [1],
                    "page_metadata": [
                        {
                            "page": 1,
                            "engine": "paddleocr",
                            "used_native_text": False,
                            "average_confidence": 0.945,
                            "preprocessing_applied": ["grayscale", "autocontrast"],
                            "warning_codes": [],
                        }
                    ],
                    "warning_codes": [],
                },
            }

            with patch(
                "extraction.parser.document_parser.validate_document_intake",
                return_value=SafetyReport(
                    sandboxed=True,
                    malware_scan_engine="local",
                    malware_scan_passed=True,
                    file_size_bytes=file_path.stat().st_size,
                    page_count=1,
                    min_resolution_dpi=300.0,
                ),
            ), patch(
                "extraction.parser.document_parser._run_parse_worker",
                side_effect=[native_result, hybrid_result],
            ):
                result = extract_document_data_with_strategy(str(file_path), strategy="auto")

        self.assertTrue(result.is_successful)
        self.assertTrue(result.used_ocr)
        self.assertIsNotNone(result.ocr_metadata)
        self.assertEqual(result.ocr_metadata.engine_used, "paddleocr")
        self.assertEqual(result.spatial_text_map[0].polygon[0], [10.0, 10.0])
        self.assertTrue(any(candidate.category == "person_name" for candidate in result.field_candidates))
        self.assertTrue(any(candidate.category == "national_identifier" for candidate in result.field_candidates))
        self.assertEqual(result.metadata.extraction_method, "hybrid")


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
