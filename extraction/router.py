from __future__ import annotations

from collections import defaultdict

from .models import OCRMetadata, OCRPageMetadata, RoutedExtraction, SpatialTextToken
from .native_extractor import extract_native_document
from .paddle_extractor import extract_paddle_text_with_confidence
from .tesseract_extractor import extract_tesseract_text

MIN_NATIVE_CHARS_PER_PAGE = 80
MIN_NATIVE_WORDS_PER_PAGE = 12


def route_extraction(pdf_path: str, strategy: str = "auto") -> RoutedExtraction:
    native_pages, native_tokens, tables_by_page = extract_native_document(pdf_path)
    page_count = len(native_pages)
    page_texts: dict[int, str] = {}
    page_confidence: dict[int, float] = {}
    page_methods: dict[int, str] = {}
    page_metadata: list[OCRPageMetadata] = []
    final_tokens_by_page: dict[int, list[SpatialTextToken]] = defaultdict(list)
    engines_used: list[str] = []
    ocr_pages: list[int] = []
    fallback_triggered = False

    native_tokens_by_page: dict[int, list[SpatialTextToken]] = defaultdict(list)
    for token in native_tokens:
        native_tokens_by_page[token.page].append(token)

    for page_num, page_payload in native_pages.items():
        native_text = str(page_payload["text"] or "").strip()
        native_word_count = int(page_payload["word_count"] or 0)
        prefer_native = strategy == "text_only"
        force_ocr = strategy == "ocr_only"
        native_good_enough = (
            len(native_text.replace(" ", "")) >= MIN_NATIVE_CHARS_PER_PAGE
            or native_word_count >= MIN_NATIVE_WORDS_PER_PAGE
        )

        if prefer_native or (not force_ocr and native_good_enough):
            page_texts[page_num] = native_text
            page_confidence[page_num] = 0.95 if native_text else 0.0
            page_methods[page_num] = "native"
            final_tokens_by_page[page_num].extend(native_tokens_by_page.get(page_num, []))
            engines_used.append("native_text")
            page_metadata.append(
                OCRPageMetadata(
                    page=page_num,
                    engine="native_text",
                    used_native_text=True,
                    average_confidence=1.0 if native_text else None,
                )
            )
            continue

        fallback_triggered = True
        ocr_pages.append(page_num)

        try:
            text, confidence, tokens = extract_paddle_text_with_confidence(pdf_path, page_num)
            engine = "paddleocr"
        except Exception:
            try:
                text, confidence, tokens = extract_tesseract_text(pdf_path, page_num)
                engine = "tesseract"
            except Exception:
                text = native_text
                confidence = 0.45 if native_text else 0.0
                tokens = native_tokens_by_page.get(page_num, [])
                engine = "native_text"

        page_texts[page_num] = text
        page_confidence[page_num] = round(float(confidence or 0.0), 4)
        page_methods[page_num] = "native" if engine == "native_text" else engine
        final_tokens_by_page[page_num].extend(tokens)
        engines_used.append(engine)
        page_metadata.append(
            OCRPageMetadata(
                page=page_num,
                engine=engine,
                used_native_text=engine == "native_text",
                average_confidence=round(float(confidence or 0.0), 4) if text else None,
            )
        )

    flat_tokens: list[SpatialTextToken] = []
    for page_num in sorted(final_tokens_by_page):
        flat_tokens.extend(final_tokens_by_page[page_num])

    unique_engines = list(dict.fromkeys(engines_used or ["native_text"]))
    avg_confidence = round(
        sum(page_confidence.values()) / max(len(page_confidence), 1),
        4,
    )
    primary_engine = next((engine for engine in unique_engines if engine != "native_text"), "native_text")
    metadata = OCRMetadata(
        method_used=primary_engine,
        fallback_triggered=fallback_triggered,
        total_pages=page_count,
        ocr_pages=sorted(ocr_pages),
        avg_confidence=avg_confidence,
        language_detected="en",
        engine_used=primary_engine,
        engines_used=unique_engines,
        native_text_used=any(entry.engine == "native_text" for entry in page_metadata),
        ocr_applied=any(entry.engine != "native_text" for entry in page_metadata),
        fallback_used=fallback_triggered,
        average_confidence=avg_confidence,
        pages_ocrd=sorted(ocr_pages),
        page_metadata=page_metadata,
    )
    return RoutedExtraction(
        page_texts=page_texts,
        spatial_tokens=flat_tokens,
        tables_by_page=tables_by_page,
        ocr_metadata=metadata,
        page_confidence=page_confidence,
        page_methods=page_methods,
        page_count=page_count,
    )
