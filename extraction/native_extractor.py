from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import fitz

from .models import SpatialTextToken


def extract_native_text(pdf_path: str) -> dict[int, str]:
    pages, _, _ = extract_native_document(pdf_path)
    return {page: payload["text"] for page, payload in pages.items()}


def extract_native_document(pdf_path: str) -> tuple[dict[int, dict], list[SpatialTextToken], dict[int, list[list[list[str]]]]]:
    document = fitz.open(str(Path(pdf_path)))
    try:
        pages: dict[int, dict] = {}
        tokens: list[SpatialTextToken] = []
        tables_by_page: dict[int, list[list[list[str]]]] = defaultdict(list)

        for page_index, page in enumerate(document, start=1):
            page_text = str(page.get_text("text", sort=True) or "").strip()
            page_tokens: list[SpatialTextToken] = []
            for word in page.get_text("words", sort=True):
                x0, y0, x1, y1, text = word[:5]
                cleaned = str(text or "").strip()
                if not cleaned:
                    continue
                token = SpatialTextToken(
                    text=cleaned,
                    bbox=[round(float(x0), 2), round(float(y0), 2), round(float(x1), 2), round(float(y1), 2)],
                    page=page_index,
                    source="native_text",
                    confidence=1.0,
                )
                page_tokens.append(token)
                tokens.append(token)

            pages[page_index] = {
                "text": page_text,
                "tokens": page_tokens,
                "word_count": len(page_tokens),
                "char_count": len("".join(page_text.split())),
                "page_width": round(float(page.rect.width), 2),
                "page_height": round(float(page.rect.height), 2),
            }
            tables_by_page[page_index].extend(_extract_page_tables(page))

        return pages, tokens, dict(tables_by_page)
    finally:
        document.close()


def _extract_page_tables(page: fitz.Page) -> list[list[list[str]]]:
    try:
        finder = getattr(page, "find_tables", None)
        if not callable(finder):
            return []
        table_result = finder()
        tables = []
        for table in getattr(table_result, "tables", []) or []:
            extracted = table.extract()
            normalized_rows: list[list[str]] = []
            for row in extracted or []:
                normalized_rows.append([str(cell or "").strip() for cell in row or []])
            if normalized_rows:
                tables.append(normalized_rows)
        return tables
    except Exception:
        return []
