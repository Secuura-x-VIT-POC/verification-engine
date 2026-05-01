from __future__ import annotations

from pathlib import Path

import fitz

from .models import SpatialTextToken


def extract_tesseract_text(pdf_path: str, page_num: int) -> tuple[str, float, list[SpatialTextToken]]:
    from extraction.ocr.engine import _extract_ocr_page_with_tesseract, load_ocr_runtime_config

    document = fitz.open(str(Path(pdf_path)))
    try:
        page = document[page_num - 1]
        payload = _extract_ocr_page_with_tesseract(page, page_num, load_ocr_runtime_config())
        tokens = [SpatialTextToken.model_validate(token) for token in payload.get("tokens", [])]
        return str(payload.get("text") or "").strip(), float(payload.get("average_confidence") or 0.0), tokens
    finally:
        document.close()
