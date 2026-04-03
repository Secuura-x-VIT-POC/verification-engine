import argparse
import io
import json
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

PAGE_DENSITY_THRESHOLD = 8.0
PAGE_WORD_THRESHOLD = 20


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR/parsing worker for PDF extraction.")
    parser.add_argument("mode", choices=["native", "ocr", "hybrid"])
    parser.add_argument("file_path")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()

    if args.mode == "native":
        payload = _extract_native(Path(args.file_path))
    elif args.mode == "ocr":
        payload = _extract_ocr(Path(args.file_path), dpi=args.dpi)
    else:
        payload = _extract_hybrid(Path(args.file_path), dpi=args.dpi)

    print(json.dumps(payload))


def _extract_native(path: Path) -> dict:
    document = fitz.open(str(path))
    spatial_map = []
    text_pages = []
    total_chars = 0
    total_area_square_inches = 0.0

    for page_index, page in enumerate(document):
        page_text = page.get_text("text", sort=True)
        text_pages.append(page_text.strip())
        total_chars += len("".join(page_text.split()))
        total_area_square_inches += (page.rect.width * page.rect.height) / (72.0 * 72.0)

        for word in page.get_text("words", sort=True):
            x0, y0, x1, y1, text = word[:5]
            cleaned = str(text).strip()
            if not cleaned:
                continue
            spatial_map.append(
                {
                    "text": cleaned,
                    "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                    "page": page_index + 1,
                }
            )

    raw_text = "\n".join(filter(None, text_pages)).strip()
    word_count = len(spatial_map)
    character_density = total_chars / total_area_square_inches if total_area_square_inches else 0.0
    return {
        "raw_text": raw_text,
        "spatial_text_map": spatial_map,
        "page_count": len(document),
        "word_count": word_count,
        "character_density": round(character_density, 4),
        "page_stats": _build_page_stats(document, spatial_map, "native_text"),
    }


def _extract_ocr(path: Path, dpi: int) -> dict:
    document = fitz.open(str(path))
    spatial_map = []
    page_texts = []
    total_chars = 0
    total_area_square_inches = 0.0
    scale = 72.0 / float(dpi)

    for page_index, page in enumerate(document):
        pixmap = page.get_pixmap(dpi=dpi)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = []
        for idx, text in enumerate(ocr_data["text"]):
            cleaned = str(text).strip()
            confidence = str(ocr_data["conf"][idx]).strip()
            if not cleaned:
                continue
            if confidence and confidence != "-1":
                try:
                    if float(confidence) < 0:
                        continue
                except ValueError:
                    pass

            left = float(ocr_data["left"][idx])
            top = float(ocr_data["top"][idx])
            width = float(ocr_data["width"][idx])
            height = float(ocr_data["height"][idx])
            token = {
                "text": cleaned,
                "bbox": [
                    round(left * scale, 2),
                    round(top * scale, 2),
                    round((left + width) * scale, 2),
                    round((top + height) * scale, 2),
                ],
                "page": page_index + 1,
            }
            spatial_map.append(token)
            words.append(cleaned)
            total_chars += len(cleaned)

        page_texts.append(" ".join(words))
        total_area_square_inches += (page.rect.width * page.rect.height) / (72.0 * 72.0)

    raw_text = "\n".join(filter(None, page_texts)).strip()
    word_count = len(spatial_map)
    character_density = total_chars / total_area_square_inches if total_area_square_inches else 0.0
    return {
        "raw_text": raw_text,
        "spatial_text_map": spatial_map,
        "page_count": len(document),
        "word_count": word_count,
        "character_density": round(character_density, 4),
        "page_stats": _build_page_stats(document, spatial_map, "ocr"),
    }


def _extract_hybrid(path: Path, dpi: int) -> dict:
    native_payload = _extract_native(path)
    document = fitz.open(str(path))
    combined_tokens = []
    page_texts = []
    page_stats = []
    total_chars = 0
    total_area_square_inches = 0.0

    native_tokens_by_page = {}
    for token in native_payload["spatial_text_map"]:
        native_tokens_by_page.setdefault(token["page"], []).append(token)

    for page_index, page in enumerate(document, start=1):
        page_tokens = native_tokens_by_page.get(page_index, [])
        page_text = " ".join(token["text"] for token in page_tokens).strip()
        page_word_count = len(page_tokens)
        page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)
        page_character_density = len("".join(page_text.split())) / page_area_square_inches if page_area_square_inches else 0.0

        if page_word_count < PAGE_WORD_THRESHOLD or page_character_density < PAGE_DENSITY_THRESHOLD:
            page_ocr_payload = _extract_ocr_page(page, page_index, dpi)
            combined_tokens.extend(page_ocr_payload["tokens"])
            page_texts.append(page_ocr_payload["text"])
            page_stats.append(
                {
                    "page": page_index,
                    "word_count": len(page_ocr_payload["tokens"]),
                    "character_density": round(page_ocr_payload["character_density"], 4),
                    "extraction_method": "ocr",
                }
            )
            total_chars += len("".join(page_ocr_payload["text"].split()))
        else:
            combined_tokens.extend(page_tokens)
            page_texts.append(page_text)
            page_stats.append(
                {
                    "page": page_index,
                    "word_count": page_word_count,
                    "character_density": round(page_character_density, 4),
                    "extraction_method": "native_text",
                }
            )
            total_chars += len("".join(page_text.split()))

        total_area_square_inches += page_area_square_inches

    raw_text = "\n".join(filter(None, page_texts)).strip()
    word_count = len(combined_tokens)
    character_density = total_chars / total_area_square_inches if total_area_square_inches else 0.0
    return {
        "raw_text": raw_text,
        "spatial_text_map": combined_tokens,
        "page_count": len(document),
        "word_count": word_count,
        "character_density": round(character_density, 4),
        "page_stats": page_stats,
    }


def _extract_ocr_page(page: fitz.Page, page_index: int, dpi: int) -> dict:
    pixmap = page.get_pixmap(dpi=dpi)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    scale = 72.0 / float(dpi)
    tokens = []
    words = []
    total_chars = 0
    page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)

    for idx, text in enumerate(ocr_data["text"]):
        cleaned = str(text).strip()
        confidence = str(ocr_data["conf"][idx]).strip()
        if not cleaned:
            continue
        if confidence and confidence != "-1":
            try:
                if float(confidence) < 0:
                    continue
            except ValueError:
                pass
        left = float(ocr_data["left"][idx])
        top = float(ocr_data["top"][idx])
        width = float(ocr_data["width"][idx])
        height = float(ocr_data["height"][idx])
        tokens.append(
            {
                "text": cleaned,
                "bbox": [
                    round(left * scale, 2),
                    round(top * scale, 2),
                    round((left + width) * scale, 2),
                    round((top + height) * scale, 2),
                ],
                "page": page_index,
                "source": "ocr",
                "confidence": 0.85,
            }
        )
        words.append(cleaned)
        total_chars += len(cleaned)

    text = " ".join(words).strip()
    character_density = total_chars / page_area_square_inches if page_area_square_inches else 0.0
    return {
        "tokens": tokens,
        "text": text,
        "character_density": character_density,
    }


def _build_page_stats(document: fitz.Document, tokens: list[dict], method: str) -> list[dict]:
    page_groups = {}
    for token in tokens:
        page_groups.setdefault(token["page"], []).append(token)

    stats = []
    for page_index, page in enumerate(document, start=1):
        page_tokens = page_groups.get(page_index, [])
        page_text = " ".join(token["text"] for token in page_tokens)
        page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)
        character_density = len("".join(page_text.split())) / page_area_square_inches if page_area_square_inches else 0.0
        stats.append(
            {
                "page": page_index,
                "word_count": len(page_tokens),
                "character_density": round(character_density, 4),
                "extraction_method": method,
            }
        )
    return stats


if __name__ == "__main__":
    main()
