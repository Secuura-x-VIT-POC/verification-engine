from __future__ import annotations

import argparse
import io
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PIL import Image, ImageFilter, ImageOps, ImageStat

try:  # pragma: no cover - import path depends on local OCR installation
    import pytesseract
except Exception:  # pragma: no cover - environment dependent
    pytesseract = None


PAGE_DENSITY_THRESHOLD = 8.0
PAGE_WORD_THRESHOLD = 20
MIN_UPSCALE_DIMENSION = 1400
LOW_CONTRAST_STDDEV_THRESHOLD = 42.0
DEFAULT_DPI = 300
DEFAULT_OCR_BACKEND_MODE = "AUTO"
SUPPORTED_OCR_BACKEND_MODES = {
    "AUTO",
    "NATIVE_ONLY",
    "PADDLE_PREFERRED",
    "TESSERACT_ONLY",
}


class OCRBackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRRuntimeConfig:
    backend_mode: str = DEFAULT_OCR_BACKEND_MODE
    dpi: int = DEFAULT_DPI
    preprocessing_enabled: bool = True
    paddle_enabled: bool = True
    paddle_language: str = "en"
    tesseract_enabled: bool = True


def load_ocr_runtime_config(*, dpi: int | None = None, backend_mode: str | None = None) -> OCRRuntimeConfig:
    resolved_mode = str(backend_mode or os.getenv("OCR_BACKEND_MODE") or DEFAULT_OCR_BACKEND_MODE).strip().upper()
    if resolved_mode not in SUPPORTED_OCR_BACKEND_MODES:
        resolved_mode = DEFAULT_OCR_BACKEND_MODE
    resolved_dpi = dpi or int(os.getenv("OCR_DPI") or DEFAULT_DPI)
    return OCRRuntimeConfig(
        backend_mode=resolved_mode,
        dpi=resolved_dpi,
        preprocessing_enabled=_parse_bool(os.getenv("OCR_PREPROCESSING_ENABLED"), default=True),
        paddle_enabled=_parse_bool(os.getenv("PADDLEOCR_ENABLED"), default=True),
        paddle_language=str(os.getenv("PADDLEOCR_LANGUAGE") or "en").strip() or "en",
        tesseract_enabled=_parse_bool(os.getenv("TESSERACT_ENABLED"), default=True),
    )


def run_local_ocr_on_page(page: fitz.Page, dpi: int = DEFAULT_DPI, backend_mode: str | None = None) -> str:
    config = load_ocr_runtime_config(dpi=dpi, backend_mode=backend_mode)
    page_payload = _extract_ocr_page_with_best_engine(page, int(page.number) + 1, config)
    return page_payload["text"]


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR/parsing worker for PDF extraction.")
    parser.add_argument("mode", choices=["native", "ocr", "hybrid"])
    parser.add_argument("file_path")
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--ocr-backend-mode", choices=sorted(SUPPORTED_OCR_BACKEND_MODES), default=None)
    args = parser.parse_args()

    target = Path(args.file_path)
    config = load_ocr_runtime_config(dpi=args.dpi, backend_mode=args.ocr_backend_mode)
    if args.mode == "native":
        payload = extract_native(target, config=config)
    elif args.mode == "ocr":
        payload = extract_ocr(target, config=config)
    else:
        payload = extract_hybrid(target, config=config)
    print(json.dumps(payload))


def extract_native(path: Path, dpi: int = DEFAULT_DPI, config: OCRRuntimeConfig | None = None) -> dict:
    runtime_config = config or load_ocr_runtime_config(dpi=dpi)
    document = fitz.open(str(path))
    try:
        spatial_map = []
        text_pages = []
        total_chars = 0
        total_area_square_inches = 0.0
        page_stats = []
        page_metadata = []

        for page_index, page in enumerate(document, start=1):
            page_text = page.get_text("text", sort=True)
            normalized_page_text = page_text.strip()
            text_pages.append(normalized_page_text)
            compact_chars = len("".join(page_text.split()))
            total_chars += compact_chars
            page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)
            total_area_square_inches += page_area_square_inches

            page_tokens = []
            for word in page.get_text("words", sort=True):
                x0, y0, x1, y1, text = word[:5]
                cleaned = str(text).strip()
                if not cleaned:
                    continue
                token = {
                    "text": cleaned,
                    "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                    "page": page_index,
                    "source": "native_text",
                    "confidence": 1.0,
                }
                page_tokens.append(token)
                spatial_map.append(token)

            character_density = compact_chars / page_area_square_inches if page_area_square_inches else 0.0
            page_stats.append(
                {
                    "page": page_index,
                    "word_count": len(page_tokens),
                    "character_density": round(character_density, 4),
                    "extraction_method": "native_text",
                    "ocr_engine": "native_text",
                }
            )
            page_metadata.append(
                {
                    "page": page_index,
                    "engine": "native_text",
                    "used_native_text": True,
                    "average_confidence": 1.0 if page_tokens else None,
                    "preprocessing_applied": [],
                    "warning_codes": [],
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
            "page_stats": page_stats,
            "ocr_metadata": _build_ocr_metadata(
                runtime_config,
                page_metadata,
                native_text_used=True,
                ocr_applied=False,
                fallback_used=False,
                warning_codes=[],
            ),
        }
    finally:
        document.close()


def extract_ocr(path: Path, dpi: int = DEFAULT_DPI, config: OCRRuntimeConfig | None = None) -> dict:
    runtime_config = config or load_ocr_runtime_config(dpi=dpi)
    if runtime_config.backend_mode == "NATIVE_ONLY":
        raise OCRBackendUnavailable("OCR backend mode NATIVE_ONLY does not permit OCR extraction.")

    document = fitz.open(str(path))
    try:
        spatial_map = []
        page_texts = []
        page_payloads = []
        total_chars = 0
        total_area_square_inches = 0.0

        for page_index, page in enumerate(document, start=1):
            page_payload = _extract_ocr_page_with_best_engine(page, page_index, runtime_config)
            page_payloads.append(page_payload)
            spatial_map.extend(page_payload["tokens"])
            page_texts.append(page_payload["text"])
            total_chars += page_payload["char_count"]
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
            "page_stats": _build_page_stats_from_payloads(page_payloads),
            "ocr_metadata": _build_ocr_metadata(
                runtime_config,
                [payload["page_metadata"] for payload in page_payloads],
                native_text_used=False,
                ocr_applied=True,
                fallback_used=any(payload["fallback_used"] for payload in page_payloads),
                warning_codes=_merge_warning_codes(page_payloads),
            ),
        }
    finally:
        document.close()


def extract_hybrid(path: Path, dpi: int = DEFAULT_DPI, config: OCRRuntimeConfig | None = None) -> dict:
    runtime_config = config or load_ocr_runtime_config(dpi=dpi)
    native_payload = extract_native(path, config=runtime_config)
    document = fitz.open(str(path))
    try:
        combined_tokens = []
        page_texts = []
        page_payloads = []
        total_chars = 0
        total_area_square_inches = 0.0

        native_tokens_by_page = {}
        for token in native_payload["spatial_text_map"]:
            native_tokens_by_page.setdefault(token["page"], []).append(token)

        native_page_stats = {
            entry["page"]: entry
            for entry in native_payload.get("page_stats", [])
            if isinstance(entry, dict) and entry.get("page") is not None
        }

        for page_index, page in enumerate(document, start=1):
            native_page_tokens = native_tokens_by_page.get(page_index, [])
            page_text = " ".join(token["text"] for token in native_page_tokens).strip()
            page_word_count = len(native_page_tokens)
            page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)
            page_character_density = len("".join(page_text.split())) / page_area_square_inches if page_area_square_inches else 0.0
            needs_ocr = page_word_count < PAGE_WORD_THRESHOLD or page_character_density < PAGE_DENSITY_THRESHOLD

            if needs_ocr and runtime_config.backend_mode != "NATIVE_ONLY":
                try:
                    page_payload = _extract_ocr_page_with_best_engine(page, page_index, runtime_config)
                except Exception as exc:
                    if native_page_tokens:
                        warning_codes = ["OCR_PAGE_FAILED_NATIVE_USED"]
                        combined_tokens.extend(native_page_tokens)
                        page_texts.append(page_text)
                        total_chars += len("".join(page_text.split()))
                        page_payloads.append(
                            {
                                "page": page_index,
                                "tokens": native_page_tokens,
                                "text": page_text,
                                "char_count": len("".join(page_text.split())),
                                "character_density": page_character_density,
                                "average_confidence": 1.0 if native_page_tokens else None,
                                "engine": "native_text",
                                "fallback_used": True,
                                "preprocessing_applied": [],
                                "warning_codes": warning_codes,
                                "page_metadata": {
                                    "page": page_index,
                                    "engine": "native_text",
                                    "used_native_text": True,
                                    "average_confidence": 1.0 if native_page_tokens else None,
                                    "preprocessing_applied": [],
                                    "warning_codes": warning_codes,
                                },
                                "page_stats": native_page_stats.get(page_index)
                                or {
                                    "page": page_index,
                                    "word_count": page_word_count,
                                    "character_density": round(page_character_density, 4),
                                    "extraction_method": "native_text",
                                    "ocr_engine": "native_text",
                                },
                            }
                        )
                    else:
                        raise RuntimeError(f"OCR failed on page {page_index}: {exc}") from exc
                else:
                    combined_tokens.extend(page_payload["tokens"])
                    page_texts.append(page_payload["text"])
                    total_chars += page_payload["char_count"]
                    page_payloads.append(page_payload)
            else:
                warning_codes = []
                if needs_ocr and runtime_config.backend_mode == "NATIVE_ONLY":
                    warning_codes.append("OCR_DISABLED_BY_MODE")
                combined_tokens.extend(native_page_tokens)
                page_texts.append(page_text)
                total_chars += len("".join(page_text.split()))
                page_payloads.append(
                    {
                        "page": page_index,
                        "tokens": native_page_tokens,
                        "text": page_text,
                        "char_count": len("".join(page_text.split())),
                        "character_density": page_character_density,
                        "average_confidence": 1.0 if native_page_tokens else None,
                        "engine": "native_text",
                        "fallback_used": False,
                        "preprocessing_applied": [],
                        "warning_codes": warning_codes,
                        "page_metadata": {
                            "page": page_index,
                            "engine": "native_text",
                            "used_native_text": True,
                            "average_confidence": 1.0 if native_page_tokens else None,
                            "preprocessing_applied": [],
                            "warning_codes": warning_codes,
                        },
                        "page_stats": native_page_stats.get(page_index)
                        or {
                            "page": page_index,
                            "word_count": page_word_count,
                            "character_density": round(page_character_density, 4),
                            "extraction_method": "native_text",
                            "ocr_engine": "native_text",
                        },
                    }
                )

            total_area_square_inches += page_area_square_inches

        raw_text = "\n".join(filter(None, page_texts)).strip()
        character_density = total_chars / total_area_square_inches if total_area_square_inches else 0.0
        return {
            "raw_text": raw_text,
            "spatial_text_map": combined_tokens,
            "page_count": len(document),
            "word_count": len(combined_tokens),
            "character_density": round(character_density, 4),
            "page_stats": _build_page_stats_from_payloads(page_payloads),
            "ocr_metadata": _build_ocr_metadata(
                runtime_config,
                [payload["page_metadata"] for payload in page_payloads],
                native_text_used=any(payload["engine"] == "native_text" for payload in page_payloads),
                ocr_applied=any(payload["engine"] != "native_text" for payload in page_payloads),
                fallback_used=any(payload["fallback_used"] for payload in page_payloads),
                warning_codes=_merge_warning_codes(page_payloads),
            ),
        }
    finally:
        document.close()


def _extract_ocr_page_with_best_engine(page: fitz.Page, page_index: int, config: OCRRuntimeConfig) -> dict[str, Any]:
    warning_codes: list[str] = []
    last_error: Exception | None = None

    for engine_name in _resolve_ocr_engine_order(config):
        try:
            if engine_name == "paddleocr":
                page_payload = _extract_ocr_page_with_paddleocr(page, page_index, config)
            else:
                page_payload = _extract_ocr_page_with_tesseract(page, page_index, config)
            if warning_codes:
                page_payload["fallback_used"] = True
                page_payload["warning_codes"] = list(dict.fromkeys([*warning_codes, *page_payload["warning_codes"]]))
                page_payload["page_metadata"]["warning_codes"] = page_payload["warning_codes"]
            return page_payload
        except OCRBackendUnavailable as exc:
            warning_codes.append(_warning_code_for_engine(engine_name))
            last_error = exc
        except Exception as exc:
            warning_codes.append(f"{engine_name.upper()}_OCR_FAILED")
            last_error = exc

    if last_error is None:
        raise OCRBackendUnavailable("No OCR backend was enabled for the requested mode.")
    raise OCRBackendUnavailable(str(last_error))


def _extract_ocr_page_with_tesseract(page: fitz.Page, page_index: int, config: OCRRuntimeConfig) -> dict[str, Any]:
    if not config.tesseract_enabled:
        raise OCRBackendUnavailable("Tesseract OCR is disabled by configuration.")
    if pytesseract is None:
        raise OCRBackendUnavailable("Tesseract OCR is unavailable because pytesseract is not installed.")

    image, preprocessing_applied = _prepare_ocr_image(page, config)
    scale_x = page.rect.width / float(image.width or 1)
    scale_y = page.rect.height / float(image.height or 1)
    ocr_data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config=os.getenv("TESSERACT_CONFIG") or "--psm 6",
    )

    tokens = []
    words = []
    confidences = []
    total_chars = 0
    page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)

    for idx, text in enumerate(ocr_data.get("text", [])):
        cleaned = str(text).strip()
        if not cleaned:
            continue
        parsed_confidence = _parse_tesseract_confidence(ocr_data.get("conf", ["-1"])[idx])
        if parsed_confidence <= 0.0:
            continue

        left = float(ocr_data["left"][idx])
        top = float(ocr_data["top"][idx])
        width = float(ocr_data["width"][idx])
        height = float(ocr_data["height"][idx])
        tokens.append(
            {
                "text": cleaned,
                "bbox": [
                    round(left * scale_x, 2),
                    round(top * scale_y, 2),
                    round((left + width) * scale_x, 2),
                    round((top + height) * scale_y, 2),
                ],
                "page": page_index,
                "source": "ocr_tesseract",
                "confidence": parsed_confidence,
            }
        )
        words.append(cleaned)
        confidences.append(parsed_confidence)
        total_chars += len(cleaned)

    text = " ".join(words).strip()
    character_density = total_chars / page_area_square_inches if page_area_square_inches else 0.0
    average_confidence = _average(confidences)
    warning_codes = ["OCR_NO_TEXT_DETECTED"] if not tokens else []
    return {
        "page": page_index,
        "tokens": tokens,
        "text": text,
        "char_count": total_chars,
        "character_density": character_density,
        "average_confidence": average_confidence,
        "engine": "tesseract",
        "fallback_used": False,
        "preprocessing_applied": preprocessing_applied,
        "warning_codes": warning_codes,
        "page_metadata": {
            "page": page_index,
            "engine": "tesseract",
            "used_native_text": False,
            "average_confidence": average_confidence,
            "preprocessing_applied": preprocessing_applied,
            "warning_codes": warning_codes,
        },
        "page_stats": {
            "page": page_index,
            "word_count": len(tokens),
            "character_density": round(character_density, 4),
            "extraction_method": "ocr",
            "ocr_engine": "tesseract",
        },
    }


def _extract_ocr_page_with_paddleocr(page: fitz.Page, page_index: int, config: OCRRuntimeConfig) -> dict[str, Any]:
    if not config.paddle_enabled:
        raise OCRBackendUnavailable("PaddleOCR is disabled by configuration.")

    image, preprocessing_applied = _prepare_ocr_image(page, config)
    scale_x = page.rect.width / float(image.width or 1)
    scale_y = page.rect.height / float(image.height or 1)
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - environment dependent
        raise OCRBackendUnavailable("PaddleOCR requires numpy in the local environment.") from exc

    paddle_ocr = _get_paddle_ocr(config.paddle_language)
    result = paddle_ocr.ocr(np.array(image), cls=True)

    tokens = []
    words = []
    confidences = []
    total_chars = 0
    page_area_square_inches = (page.rect.width * page.rect.height) / (72.0 * 72.0)

    for polygon, text, confidence in _iter_paddle_entries(result):
        cleaned = str(text).strip()
        if not cleaned:
            continue
        pdf_polygon = [[round(point[0] * scale_x, 2), round(point[1] * scale_y, 2)] for point in polygon]
        x_values = [point[0] for point in pdf_polygon]
        y_values = [point[1] for point in pdf_polygon]
        tokens.append(
            {
                "text": cleaned,
                "bbox": [
                    round(min(x_values), 2),
                    round(min(y_values), 2),
                    round(max(x_values), 2),
                    round(max(y_values), 2),
                ],
                "polygon": pdf_polygon,
                "page": page_index,
                "source": "ocr_paddleocr",
                "confidence": round(float(confidence or 0.0), 4),
            }
        )
        words.append(cleaned)
        confidences.append(float(confidence or 0.0))
        total_chars += len(cleaned)

    text = " ".join(words).strip()
    character_density = total_chars / page_area_square_inches if page_area_square_inches else 0.0
    average_confidence = _average(confidences)
    warning_codes = ["OCR_NO_TEXT_DETECTED"] if not tokens else []
    return {
        "page": page_index,
        "tokens": tokens,
        "text": text,
        "char_count": total_chars,
        "character_density": character_density,
        "average_confidence": average_confidence,
        "engine": "paddleocr",
        "fallback_used": False,
        "preprocessing_applied": preprocessing_applied,
        "warning_codes": warning_codes,
        "page_metadata": {
            "page": page_index,
            "engine": "paddleocr",
            "used_native_text": False,
            "average_confidence": average_confidence,
            "preprocessing_applied": preprocessing_applied,
            "warning_codes": warning_codes,
        },
        "page_stats": {
            "page": page_index,
            "word_count": len(tokens),
            "character_density": round(character_density, 4),
            "extraction_method": "ocr",
            "ocr_engine": "paddleocr",
        },
    }


def _prepare_ocr_image(page: fitz.Page, config: OCRRuntimeConfig) -> tuple[Image.Image, list[str]]:
    pixmap = page.get_pixmap(dpi=config.dpi, alpha=False)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    if not config.preprocessing_enabled:
        return image, []
    return _preprocess_image(image)


def _preprocess_image(image: Image.Image) -> tuple[Image.Image, list[str]]:
    steps: list[str] = []
    processed = ImageOps.exif_transpose(image)
    if processed.mode != "L":
        processed = ImageOps.grayscale(processed)
        steps.append("grayscale")

    processed = ImageOps.autocontrast(processed, cutoff=1)
    steps.append("autocontrast")

    processed = processed.filter(ImageFilter.MedianFilter(size=3))
    steps.append("median_denoise")

    processed = processed.filter(ImageFilter.SHARPEN)
    steps.append("sharpen")

    smallest_dimension = min(processed.size)
    if smallest_dimension and smallest_dimension < MIN_UPSCALE_DIMENSION:
        scale_factor = MIN_UPSCALE_DIMENSION / float(smallest_dimension)
        processed = processed.resize(
            (
                max(1, int(round(processed.width * scale_factor))),
                max(1, int(round(processed.height * scale_factor))),
            ),
            Image.Resampling.LANCZOS,
        )
        steps.append(f"upscale_{round(scale_factor, 2)}x")

    stddev = float(ImageStat.Stat(processed).stddev[0] or 0.0)
    if stddev < LOW_CONTRAST_STDDEV_THRESHOLD:
        threshold = _dynamic_threshold(processed)
        processed = processed.point(lambda pixel: 255 if pixel >= threshold else 0)
        steps.append("threshold_binarize")

    return processed, steps


def _dynamic_threshold(image: Image.Image) -> int:
    stat = ImageStat.Stat(image)
    mean_value = float(stat.mean[0] or 0.0)
    return max(96, min(188, int(round(mean_value * 0.92))))


def _resolve_ocr_engine_order(config: OCRRuntimeConfig) -> list[str]:
    if config.backend_mode == "TESSERACT_ONLY":
        return ["tesseract"]
    if config.backend_mode in {"AUTO", "PADDLE_PREFERRED"}:
        return ["paddleocr", "tesseract"]
    if config.backend_mode == "NATIVE_ONLY":
        return []
    return ["paddleocr", "tesseract"]


@lru_cache(maxsize=4)
def _get_paddle_ocr(language: str):  # pragma: no cover - depends on local OCR install
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        raise OCRBackendUnavailable("PaddleOCR is unavailable because the paddleocr package is not installed.") from exc
    try:
        return PaddleOCR(use_angle_cls=True, lang=language, show_log=False)
    except Exception as exc:
        raise OCRBackendUnavailable(f"PaddleOCR could not initialize locally: {exc}") from exc


def _iter_paddle_entries(result: Any) -> list[tuple[list[list[float]], str, float]]:
    if result is None:
        return []

    entries = []
    blocks = result
    if isinstance(blocks, list) and len(blocks) == 1 and isinstance(blocks[0], list):
        blocks = blocks[0]

    for block in blocks or []:
        if not isinstance(block, (list, tuple)) or len(block) < 2:
            continue
        polygon = _coerce_polygon(block[0])
        if not polygon:
            continue
        text_payload = block[1]
        if isinstance(text_payload, (list, tuple)) and text_payload:
            text = str(text_payload[0])
            confidence = float(text_payload[1]) if len(text_payload) > 1 else 0.0
        elif isinstance(text_payload, dict):
            text = str(text_payload.get("text") or "")
            confidence = float(text_payload.get("confidence") or 0.0)
        else:
            text = str(text_payload)
            confidence = 0.0
        entries.append((polygon, text, confidence))
    return entries


def _coerce_polygon(value: Any) -> list[list[float]]:
    polygon = []
    for point in value or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        polygon.append([float(point[0]), float(point[1])])
    return polygon


def _build_page_stats_from_payloads(page_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [payload["page_stats"] for payload in page_payloads]


def _build_ocr_metadata(
    config: OCRRuntimeConfig,
    page_metadata: list[dict[str, Any]],
    *,
    native_text_used: bool,
    ocr_applied: bool,
    fallback_used: bool,
    warning_codes: list[str],
) -> dict[str, Any]:
    engines_used = []
    preprocessing_applied = []
    pages_ocrd = []
    confidences = []

    for page_entry in page_metadata:
        engine = str(page_entry.get("engine") or "native_text")
        if engine not in engines_used:
            engines_used.append(engine)
        if not page_entry.get("used_native_text"):
            pages_ocrd.append(int(page_entry.get("page") or 0))
        preprocessing_applied.extend(page_entry.get("preprocessing_applied") or [])
        if page_entry.get("average_confidence") is not None:
            confidences.append(float(page_entry["average_confidence"]))

    ocr_engines = [engine for engine in engines_used if engine != "native_text"]
    primary_engine = ocr_engines[0] if ocr_engines else "native_text"
    return {
        "backend_mode": config.backend_mode,
        "engine_used": primary_engine,
        "engines_used": engines_used or ["native_text"],
        "native_text_used": native_text_used,
        "ocr_applied": ocr_applied,
        "fallback_used": fallback_used,
        "average_confidence": _average(confidences),
        "preprocessing_applied": list(dict.fromkeys(preprocessing_applied)),
        "pages_ocrd": [page for page in pages_ocrd if page > 0],
        "page_metadata": page_metadata,
        "warning_codes": list(dict.fromkeys(warning_codes)),
    }


def _merge_warning_codes(page_payloads: list[dict[str, Any]]) -> list[str]:
    warning_codes: list[str] = []
    for payload in page_payloads:
        warning_codes.extend(payload.get("warning_codes") or [])
    return list(dict.fromkeys(warning_codes))


def _warning_code_for_engine(engine_name: str) -> str:
    if engine_name == "paddleocr":
        return "PADDLEOCR_UNAVAILABLE"
    return "TESSERACT_UNAVAILABLE"


def _parse_tesseract_confidence(value: Any) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0
    if parsed < 0:
        return 0.0
    if parsed > 1.0:
        parsed = parsed / 100.0
    return round(parsed, 4)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


if __name__ == "__main__":
    main()
