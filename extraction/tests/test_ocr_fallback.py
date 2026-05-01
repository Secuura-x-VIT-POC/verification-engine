from __future__ import annotations

import unittest
from unittest.mock import patch

from extraction.models import SpatialTextToken
from extraction.router import route_extraction


class OCRFallbackTests(unittest.TestCase):
    def test_router_uses_ocr_when_native_text_sparse(self):
        native_pages = {
            1: {
                "text": "",
                "tokens": [],
                "word_count": 0,
                "char_count": 0,
                "page_width": 595.0,
                "page_height": 842.0,
            }
        }
        ocr_tokens = [SpatialTextToken(text="Asha", bbox=[1, 1, 10, 10], page=1, source="ocr_paddleocr", confidence=0.94)]
        with patch(
            "extraction.router.extract_native_document",
            return_value=(native_pages, [], {}),
        ), patch(
            "extraction.router.extract_paddle_text_with_confidence",
            return_value=("Asha Rao", 0.94, ocr_tokens),
        ):
            routed = route_extraction("synthetic.pdf", strategy="auto")

        self.assertTrue(routed.ocr_metadata.ocr_applied)
        self.assertEqual(routed.ocr_metadata.engine_used, "paddleocr")
        self.assertEqual(routed.page_methods[1], "paddleocr")
