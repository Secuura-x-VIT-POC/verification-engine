from __future__ import annotations

import contextlib
import hashlib
import inspect
import importlib.metadata
import io
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SOURCE = "pp_chatocr_v4"
COORDINATE_SPACE = "pp_chatocr_image_pixels"
PIPELINE_NAME = "PP-ChatOCRv4-doc"
LOGGER = logging.getLogger(__name__)

DEFAULT_KEY_LIST = [
    "all visible key-value pairs",
    "all named entities and labels",
    "all document identifiers",
    "all dates",
    "all monetary amounts",
    "all organizations",
    "all people",
    "all addresses or locations",
    "all eligibility/status/result fields",
]

UNRESOLVED_VALUES = {"", "no", "none", "null", "unknown", "not found", "n/a", "na", "未找到关键信息"}


class PPChatOCRConfigurationError(RuntimeError):
    pass


class PPChatOCRExtractionError(RuntimeError):
    pass


def run_pp_chatocr_v4_extraction(
    file_path: str,
    key_list: list[str] | None = None,
    document_type_hint: str | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    config = _load_config()
    keys = _normalize_key_list(key_list, document_type_hint)

    try:
        from paddleocr import PPChatOCRv4Doc
    except Exception as exc:  # pragma: no cover - environment dependent
        raise PPChatOCRConfigurationError("PP-ChatOCRv4-doc is unavailable: paddleocr.PPChatOCRv4Doc could not be imported.") from exc

    try:
        engine = PPChatOCRv4Doc(
            device=config["device"],
            use_table_recognition=config["use_table_recognition"],
            use_seal_recognition=config["use_seal_recognition"],
            use_doc_orientation_classify=config["use_doc_orientation_classify"],
            use_doc_unwarping=config["use_doc_unwarping"],
        )
    except Exception as exc:  # pragma: no cover - model init is environment dependent
        raise PPChatOCRConfigurationError(f"PP-ChatOCRv4-doc could not initialize: {_safe_error(exc)}") from exc

    warnings: list[str] = []
    try:
        with _prepare_pp_inputs(path) as pp_inputs:
            visual_results = []
            for input_item in pp_inputs:
                with _suppress_pp_console_output():
                    page_visual_results = list(
                        engine.visual_predict(
                            input_item["path"],
                            use_table_recognition=config["use_table_recognition"],
                            use_seal_recognition=config["use_seal_recognition"],
                            use_doc_orientation_classify=config["use_doc_orientation_classify"],
                            use_doc_unwarping=config["use_doc_unwarping"],
                        )
                    )
                for result in page_visual_results:
                    if isinstance(result, dict):
                        result["_pp_page_number"] = input_item["page_number"]
                        result["_pp_source_width"] = input_item.get("source_width")
                        result["_pp_source_height"] = input_item.get("source_height")
                visual_results.extend(page_visual_results)

            visual_info_list = [item.get("visual_info") for item in visual_results if isinstance(item, dict) and item.get("visual_info") is not None]
            normalized = _normalize_visual_results(visual_results)
            if not _has_usable_visual_ocr(normalized):
                raise PPChatOCRExtractionError("PP-ChatOCRv4 visual/layout OCR produced no usable text lines with boxes.")

            vector_info = None
            try:
                vector_info = _call_with_supported_kwargs(
                    engine.build_vector,
                    visual_info_list,
                    retriever_config=config["retriever_config"],
                )
            except Exception as exc:
                warnings.append("pp_chatocr_vector_stage_failed")
                _log_safe_stage_error("vector", exc, fallback_used=True)

            mllm_predict_info = None
            mllm_results = []
            if config["mllm_chat_bot_config"]:
                try:
                    for input_item in pp_inputs:
                        mllm_result = _call_with_supported_kwargs(
                            engine.mllm_pred,
                            input_item["path"],
                            keys,
                            mllm_chat_bot_config=config["mllm_chat_bot_config"],
                        )
                        page_mllm = _as_mapping(mllm_result).get("mllm_res")
                        if isinstance(page_mllm, dict):
                            mllm_results.append(page_mllm)
                except Exception as exc:
                    warnings.append(_stage_warning_code("mllm", exc))
                    _log_safe_stage_error("mllm", exc, fallback_used=False)
            mllm_predict_info = _merge_prediction_maps(mllm_results)

            chat_result = None
            if config["chat_bot_config"]:
                try:
                    chat_result = _call_with_supported_kwargs(
                        engine.chat,
                        keys,
                        visual_info_list,
                        vector_info=vector_info,
                        mllm_predict_info=mllm_predict_info,
                        chat_bot_config=config["chat_bot_config"],
                    )
                except Exception as exc:
                    warnings.append(_stage_warning_code("chat", exc))
                    _log_safe_stage_error("chat", exc, fallback_used=False)
            else:
                warnings.append("pp_chatocr_chat_stage_disabled")
    except (PPChatOCRConfigurationError, PPChatOCRExtractionError):
        raise
    except Exception as exc:
        raise PPChatOCRExtractionError(f"PP-ChatOCRv4-doc extraction failed: {_safe_error(exc)}") from exc
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    chat_fields = _normalize_prediction_map(_as_mapping(chat_result).get("chat_res"))
    mllm_fields = _normalize_prediction_map(mllm_predict_info)
    predictions = [*chat_fields, *mllm_fields] or _prediction_fields_from_visual_ocr(normalized)
    field_candidates = _build_field_candidates(predictions, normalized, warnings)

    return {
        "extraction_method": SOURCE,
        "ocr_performed": True,
        "advanced_ocr_performed": True,
        "field_candidates": field_candidates,
        "evidence_lines": normalized["evidence_lines"],
        "layout_blocks": normalized["layout_blocks"],
        "table_cells": normalized["table_cells"],
        "spatial_text_map": normalized["spatial_text_map"],
        "page_count": normalized["page_count"],
        "field_count": len(field_candidates),
        "warnings": list(dict.fromkeys(warnings + normalized["warnings"])),
        "ocr_metadata": {
            "method_used": SOURCE,
            "engine_used": SOURCE,
            "engines_used": [SOURCE],
            "pipeline": PIPELINE_NAME,
            "device": config["device"],
            "ocr_applied": True,
            "advanced_ocr_performed": True,
            "native_text_used": False,
            "fallback_used": False,
            "fallback_triggered": False,
            "total_pages": normalized["page_count"],
            "ocr_pages": list(range(1, normalized["page_count"] + 1)),
            "pages_ocrd": list(range(1, normalized["page_count"] + 1)),
            "avg_confidence": _average_confidence(normalized["spatial_text_map"]),
            "average_confidence": _average_confidence(normalized["spatial_text_map"]),
            "warning_codes": list(dict.fromkeys(warnings + normalized["warnings"])),
        },
        "engine_metadata": {
            "source": SOURCE,
            "pipeline": PIPELINE_NAME,
            "coordinate_space": COORDINATE_SPACE,
            "paddleocr_version": _package_version("paddleocr"),
            "paddlex_version": _package_version("paddlex"),
            "paddlepaddle_version": _package_version("paddlepaddle"),
            "chat_configured": bool(config["chat_bot_config"]),
            "retriever_configured": bool(config["retriever_config"]),
            "mllm_configured": bool(config["mllm_chat_bot_config"]),
        },
    }


def _load_config() -> dict[str, Any]:
    required = [
        "SECUURA_OCR_ENGINE",
        "SECUURA_ENABLE_ADVANCED_PADDLE_OCR",
        "PP_CHAT_OCR_PIPELINE",
        "PP_CHAT_OCR_DEVICE",
        "PP_CHAT_OCR_ENABLE_TABLE_RECOGNITION",
        "PP_CHAT_OCR_ENABLE_SEAL_RECOGNITION",
        "PP_CHAT_OCR_ENABLE_DOC_ORIENTATION",
        "PP_CHAT_OCR_ENABLE_DOC_UNWARPING",
    ]
    missing = [name for name in required if os.getenv(name) in (None, "")]
    if missing:
        raise PPChatOCRConfigurationError(f"Missing required PP-ChatOCRv4 configuration: {', '.join(missing)}.")

    engine = os.getenv("SECUURA_OCR_ENGINE", "").strip().lower()
    if engine != SOURCE:
        raise PPChatOCRConfigurationError("SECUURA_OCR_ENGINE must be pp_chatocr_v4.")
    if not _parse_bool(os.getenv("SECUURA_ENABLE_ADVANCED_PADDLE_OCR"), default=True):
        raise PPChatOCRConfigurationError("SECUURA_ENABLE_ADVANCED_PADDLE_OCR must be true.")
    pipeline = os.getenv("PP_CHAT_OCR_PIPELINE", "").strip()
    if pipeline != PIPELINE_NAME:
        raise PPChatOCRConfigurationError("PP_CHAT_OCR_PIPELINE must be PP-ChatOCRv4-doc.")

    device = os.getenv("PP_CHAT_OCR_DEVICE", "").strip()
    if device.lower().startswith("gpu") and _package_version("paddlepaddle-gpu") is None:
        raise PPChatOCRConfigurationError("PP_CHAT_OCR_DEVICE requests GPU, but paddlepaddle-gpu is not installed. Install GPU Paddle or set PP_CHAT_OCR_DEVICE=cpu.")

    return {
        "device": device,
        "use_table_recognition": _parse_bool(os.getenv("PP_CHAT_OCR_ENABLE_TABLE_RECOGNITION"), default=True),
        "use_seal_recognition": _parse_bool(os.getenv("PP_CHAT_OCR_ENABLE_SEAL_RECOGNITION"), default=True),
        "use_doc_orientation_classify": _parse_bool(os.getenv("PP_CHAT_OCR_ENABLE_DOC_ORIENTATION"), default=True),
        "use_doc_unwarping": _parse_bool(os.getenv("PP_CHAT_OCR_ENABLE_DOC_UNWARPING"), default=True),
        "chat_bot_config": _build_bot_config("PP_CHAT_OCR_CHAT"),
        "retriever_config": _build_bot_config("PP_CHAT_OCR_RETRIEVER"),
        "mllm_chat_bot_config": _build_bot_config("PP_CHAT_OCR_MLLM"),
    }


class _PreparedPPInputs:
    def __init__(self, path: Path):
        self.path = path
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.items: list[dict[str, Any]] = []

    def __enter__(self) -> list[dict[str, Any]]:
        if self.path.suffix.lower() == ".pdf":
            self._temp_dir = tempfile.TemporaryDirectory(prefix="secuura_pp_chatocr_pdf_")
            self.items = _rasterize_pdf_to_images(self.path, Path(self._temp_dir.name))
        else:
            width, height = _image_size(self.path)
            self.items = [
                {
                    "path": str(self.path),
                    "page_number": 1,
                    "source_width": width,
                    "source_height": height,
                }
            ]
        return self.items

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()


def _prepare_pp_inputs(path: Path) -> _PreparedPPInputs:
    return _PreparedPPInputs(path)


def _rasterize_pdf_to_images(path: Path, output_dir: Path) -> list[dict[str, Any]]:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - environment dependent
        raise PPChatOCRConfigurationError("PDF rasterization requires PyMuPDF for image rendering only.") from exc

    items: list[dict[str, Any]] = []
    try:
        document = fitz.open(str(path))
        try:
            for page_index in range(len(document)):
                page = document.load_page(page_index)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = output_dir / f"page-{page_index + 1}.png"
                pix.save(str(image_path))
                items.append(
                    {
                        "path": str(image_path),
                        "page_number": page_index + 1,
                        "source_width": int(pix.width),
                        "source_height": int(pix.height),
                    }
                )
        finally:
            document.close()
    except Exception as exc:
        raise PPChatOCRExtractionError(f"PDF rasterization for PP-ChatOCR failed: {_safe_error(exc)}") from exc
    if not items:
        raise PPChatOCRExtractionError("PDF rasterization for PP-ChatOCR produced no page images.")
    return items


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None, None


def _build_bot_config(prefix: str) -> dict[str, Any] | None:
    config = {
        "api_key": os.getenv(f"{prefix}_API_KEY", "").strip(),
        "base_url": os.getenv(f"{prefix}_BASE_URL", "").strip(),
        "model_name": os.getenv(f"{prefix}_MODEL_NAME", "").strip(),
    }
    filtered = {key: value for key, value in config.items() if value}
    return filtered or None


def _call_with_supported_kwargs(callable_obj, *args, **kwargs):
    filtered_kwargs = {key: value for key, value in kwargs.items() if value is not None}
    if not filtered_kwargs:
        with _suppress_pp_console_output():
            return callable_obj(*args)
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        with _suppress_pp_console_output():
            return callable_obj(*args, **filtered_kwargs)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        with _suppress_pp_console_output():
            return callable_obj(*args, **filtered_kwargs)
    supported = {key: value for key, value in filtered_kwargs.items() if key in signature.parameters}
    with _suppress_pp_console_output():
        return callable_obj(*args, **supported)


@contextlib.contextmanager
def _suppress_pp_console_output():
    if _parse_bool(os.getenv("SECUURA_PP_CHAT_OCR_VERBOSE"), default=False):
        yield
        return
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def _merge_prediction_maps(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for item in items:
        for key, value in item.items():
            if key not in merged or _is_unresolved_value(_sanitize_value(merged.get(key))):
                merged[key] = value
    return merged or None


def _first_non_null(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_visual_results(visual_results: list[Any]) -> dict[str, Any]:
    spatial_text_map: list[dict[str, Any]] = []
    evidence_lines: list[dict[str, Any]] = []
    layout_blocks: list[dict[str, Any]] = []
    table_cells: list[dict[str, Any]] = []
    warnings: list[str] = []

    for page_index, result in enumerate(visual_results or [], start=1):
        if not isinstance(result, dict):
            continue
        layout = _safe_result_mapping(
            result.get("layout_parsing_result")
            or result.get("layoutParsingResults")
            or result.get("visual_info")
            or result
        )
        page_number = _coerce_int(result.get("_pp_page_number") or layout.get("page_index") or layout.get("page_id") or layout.get("page_number"), page_index)
        source_width = _coerce_int(result.get("_pp_source_width"), None)
        source_height = _coerce_int(result.get("_pp_source_height"), None)

        for block_index, block in enumerate(_as_list(layout.get("parsing_res_list") or layout.get("prunedResult")), start=1):
            block_map = _as_mapping(block)
            text = _sanitize_preview(block_map.get("block_content") or block_map.get("content"))
            geom = _geometry(
                page_number,
                _first_non_null(block_map.get("block_bbox"), block_map.get("bbox")),
                _first_non_null(block_map.get("block_polygon"), block_map.get("polygon")),
                None,
                source_width=source_width,
                source_height=source_height,
            )
            layout_block = {
                "layout_block_id": f"layout-{page_number}-{block_index}",
                "block_label": str(block_map.get("block_label") or block_map.get("label") or "text"),
                "text_preview": text,
                **geom,
            }
            layout_blocks.append(layout_block)
            if text:
                evidence_lines.append(
                    {
                        "evidence_line_id": f"ev-layout-{page_number}-{block_index}",
                        "text_preview": text,
                        **geom,
                    }
                )

        _append_ocr_tokens(
            layout.get("overall_ocr_res") or result.get("overall_ocr_res"),
            page_number=page_number,
            source_width=source_width,
            source_height=source_height,
            source_kind="ocr",
            spatial_text_map=spatial_text_map,
            evidence_lines=evidence_lines,
        )

        for table_index, table in enumerate(_as_list(layout.get("table_res_list") or result.get("table_res_list")), start=1):
            table_map = _as_mapping(table)
            for cell_index, cell_box in enumerate(_as_list(table_map.get("cell_bbox_list")), start=1):
                table_cells.append(
                    {
                        "table_cell_id": f"table-{page_number}-{table_index}-{cell_index}",
                        "text_preview": "",
                        **_geometry(page_number, cell_box, None, None, source_width=source_width, source_height=source_height),
                    }
                )
            _append_table_tokens(
                table_map.get("table_ocr_pred"),
                page_number=page_number,
                table_index=table_index,
                source_width=source_width,
                source_height=source_height,
                spatial_text_map=spatial_text_map,
                evidence_lines=evidence_lines,
                table_cells=table_cells,
            )
            _append_ocr_tokens(
                table_map.get("seal_ocr_res") or table_map.get("seal_res") or table_map.get("seal_ocr_pred"),
                page_number=page_number,
                source_width=source_width,
                source_height=source_height,
                source_kind="seal",
                spatial_text_map=spatial_text_map,
                evidence_lines=evidence_lines,
            )

    if not spatial_text_map and not layout_blocks:
        warnings.append("pp_chatocr_no_visual_text")

    return {
        "spatial_text_map": spatial_text_map,
        "evidence_lines": evidence_lines,
        "layout_blocks": layout_blocks,
        "table_cells": table_cells,
        "page_count": max([1, *[int(item.get("page_number") or 1) for item in [*spatial_text_map, *layout_blocks, *table_cells]]]),
        "warnings": warnings,
    }


def _has_usable_visual_ocr(normalized: dict[str, Any]) -> bool:
    return any(item.get("text_preview") and item.get("bbox") for item in normalized.get("spatial_text_map") or [])


def _prediction_fields_from_visual_ocr(normalized: dict[str, Any]) -> list[dict[str, str]]:
    predictions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(normalized.get("evidence_lines") or [], start=1):
        text = _sanitize_value(item.get("text_preview"))
        if not text or text in seen:
            continue
        seen.add(text)
        predictions.append({"label": f"Visible Text {index}", "value": text})
    return predictions


def _stage_warning_code(stage: str, exc: Exception) -> str:
    if _is_auth_error(exc):
        return f"pp_chatocr_{stage}_auth_failed"
    return f"pp_chatocr_{stage}_stage_failed"


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "401" in text or "invalid_iam_token" in text or "unauthorized" in text


def _log_safe_stage_error(stage: str, exc: Exception, *, fallback_used: bool) -> None:
    LOGGER.warning(
        "PP_CHAT_OCR_STAGE_FAILED component=pp_chatocr stage=%s error_code=%s exception_class=%s fallback_used=%s",
        stage,
        "401" if _is_auth_error(exc) else "unknown",
        exc.__class__.__name__,
        fallback_used,
    )


def _append_ocr_tokens(raw_ocr: Any, *, page_number: int, source_width: int | None = None, source_height: int | None = None, source_kind: str, spatial_text_map: list[dict[str, Any]], evidence_lines: list[dict[str, Any]]) -> None:
    ocr = _as_mapping(raw_ocr)
    rec_texts = _as_list(ocr.get("rec_texts"))
    rec_scores = _as_list(ocr.get("rec_scores"))
    rec_polys = _as_list(ocr.get("rec_polys")) or _as_list(ocr.get("dt_polys"))
    rec_boxes = _as_list(ocr.get("rec_boxes"))
    dt_scores = _as_list(ocr.get("dt_scores"))
    for index, text_value in enumerate(rec_texts, start=1):
        text = _sanitize_preview(text_value)
        if not text:
            continue
        confidence = _coerce_float(_index_or_none(rec_scores, index - 1), _coerce_float(_index_or_none(dt_scores, index - 1), None))
        geom = _geometry(page_number, _index_or_none(rec_boxes, index - 1), _index_or_none(rec_polys, index - 1), confidence, source_width=source_width, source_height=source_height)
        token = {
            "token_id": f"{source_kind}-{page_number}-{index}",
            "text_preview": text,
            "source_kind": source_kind,
            **geom,
        }
        spatial_text_map.append(token)
        evidence_lines.append(
            {
                "evidence_line_id": f"ev-{source_kind}-{page_number}-{index}",
                "text_preview": text,
                **geom,
            }
        )


def _append_table_tokens(raw_table_ocr: Any, *, page_number: int, table_index: int, source_width: int | None = None, source_height: int | None = None, spatial_text_map: list[dict[str, Any]], evidence_lines: list[dict[str, Any]], table_cells: list[dict[str, Any]]) -> None:
    before_count = len(spatial_text_map)
    _append_ocr_tokens(
        raw_table_ocr,
        page_number=page_number,
        source_width=source_width,
        source_height=source_height,
        source_kind=f"table-{table_index}",
        spatial_text_map=spatial_text_map,
        evidence_lines=evidence_lines,
    )
    for token_index, token in enumerate(spatial_text_map[before_count:], start=1):
        table_cells.append(
            {
                "table_cell_id": f"table-token-{page_number}-{table_index}-{token_index}",
                "text_preview": token.get("text_preview") or "",
                "page_number": token.get("page_number"),
                "bbox": token.get("bbox"),
                "polygon": token.get("polygon"),
                "coordinate_space": COORDINATE_SPACE,
                "source": SOURCE,
                "confidence": token.get("confidence"),
                "source_width": token.get("source_width"),
                "source_height": token.get("source_height"),
            }
        )


def _build_field_candidates(predictions: list[dict[str, str]], normalized: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, prediction in enumerate(predictions, start=1):
        label = _sanitize_label(prediction.get("label"))
        value = _sanitize_value(prediction.get("value"))
        if not label or _is_unresolved_value(value):
            continue
        match = _match_geometry_for_value(value, normalized)
        if match is None:
            match = _nearest_layout_geometry(normalized)
            if match is None:
                warnings.append("bbox_unresolved")
                match = _geometry(1, None, None, None)
            else:
                warnings.append("bbox_unresolved")
        field_id = _field_id(label, value, index)
        candidates.append(
            {
                "field_id": field_id,
                "label": label,
                "extracted_value": value,
                "masked_value": _mask_value(value),
                "normalized_value": value,
                "confidence": match.get("confidence") if match.get("confidence") is not None else 0.85,
                "page_number": match.get("page_number"),
                "page": match.get("page_number"),
                "bbox": match.get("bbox"),
                "polygon": match.get("polygon"),
                "coordinate_space": COORDINATE_SPACE,
                "source": SOURCE,
                "source_width": match.get("source_width"),
                "source_height": match.get("source_height"),
                "evidence_ref": _find_evidence_ref(value, normalized.get("evidence_lines") or []),
                "evidence_line_id": _find_evidence_ref(value, normalized.get("evidence_lines") or []),
                "extraction_method": SOURCE,
                "ocr_performed": True,
                "advanced_ocr_performed": True,
                "category": _category_for_label(label),
                "requires_verification": True,
                "bounding_box": _box_dict(match),
                "bounding_boxes": [_box_dict(match)] if match.get("bbox") else [],
            }
        )
    return candidates


def _match_geometry_for_value(value: str, normalized: dict[str, Any]) -> dict[str, Any] | None:
    tokens = [token for token in normalized.get("spatial_text_map") or [] if token.get("text_preview")]
    wanted = _norm(value)
    if not wanted:
        return None
    for token in tokens:
        if _norm(token.get("text_preview")) == wanted:
            return _copy_geometry(token)

    pieces = [piece for piece in re.split(r"\s+", wanted) if piece]
    if len(pieces) >= 2:
        matched = []
        start = 0
        for piece in pieces:
            found = None
            for idx in range(start, len(tokens)):
                if _norm(tokens[idx].get("text_preview")) == piece:
                    found = idx
                    break
            if found is None:
                matched = []
                break
            matched.append(tokens[found])
            start = found + 1
        if matched:
            return _combine_geometries(matched)

    for token in tokens:
        token_text = _norm(token.get("text_preview"))
        if wanted in token_text or token_text in wanted:
            return _copy_geometry(token)
    return None


def _nearest_layout_geometry(normalized: dict[str, Any]) -> dict[str, Any] | None:
    for item in normalized.get("layout_blocks") or []:
        if item.get("bbox") or item.get("polygon"):
            return _copy_geometry(item)
    for item in normalized.get("table_cells") or []:
        if item.get("bbox") or item.get("polygon"):
            return _copy_geometry(item)
    return None


def _combine_geometries(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    boxes = [item.get("bbox") for item in items if item.get("bbox")]
    polygons = [point for item in items for point in (item.get("polygon") or [])]
    if not boxes and not polygons:
        return None
    bbox = _bbox_from_points(polygons) if polygons else _merge_boxes(boxes)
    return {
        "page_number": items[0].get("page_number") or 1,
        "bbox": bbox,
        "polygon": polygons or None,
        "coordinate_space": COORDINATE_SPACE,
        "source": SOURCE,
        "confidence": _average_confidence(items),
        "source_width": next((item.get("source_width") for item in items if item.get("source_width")), None),
        "source_height": next((item.get("source_height") for item in items if item.get("source_height")), None),
    }


def _normalize_prediction_map(value: Any) -> list[dict[str, str]]:
    mapping = _as_mapping(value)
    results = []
    for key, raw_value in mapping.items():
        if isinstance(raw_value, dict):
            candidate_value = raw_value.get("value") or raw_value.get("extracted_value") or raw_value.get("normalized_value") or raw_value.get("text")
        else:
            candidate_value = raw_value
        label = _sanitize_label(key)
        text = _sanitize_value(candidate_value)
        if label and not _is_unresolved_value(text):
            results.append({"label": label, "value": text})
    return results


def _geometry(page_number: int, bbox: Any, polygon: Any, confidence: Any, *, source_width: int | None = None, source_height: int | None = None) -> dict[str, Any]:
    coerced_polygon = _coerce_polygon(polygon)
    coerced_bbox = _coerce_bbox(bbox) or (_bbox_from_points(coerced_polygon) if coerced_polygon else None)
    return {
        "page_number": int(page_number or 1),
        "bbox": coerced_bbox,
        "polygon": coerced_polygon,
        "coordinate_space": COORDINATE_SPACE,
        "source": SOURCE,
        "confidence": _coerce_float(confidence, None),
        "source_width": source_width,
        "source_height": source_height,
    }


def _box_dict(geom: dict[str, Any]) -> dict[str, Any] | None:
    bbox = geom.get("bbox")
    if not bbox:
        return None
    return {
        "page": int(geom.get("page_number") or 1),
        "page_number": int(geom.get("page_number") or 1),
        "x0": float(bbox[0]),
        "y0": float(bbox[1]),
        "x1": float(bbox[2]),
        "y1": float(bbox[3]),
        "bbox": list(bbox),
        "polygon": geom.get("polygon"),
        "coordinate_space": COORDINATE_SPACE,
        "source": SOURCE,
        "confidence": geom.get("confidence"),
        "source_width": geom.get("source_width"),
        "source_height": geom.get("source_height"),
    }


def _safe_result_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value:
        return _safe_result_mapping(value[0])
    if isinstance(value, dict):
        return value
    json_attr = getattr(value, "json", None)
    if isinstance(json_attr, dict) and isinstance(json_attr.get("res"), dict):
        return json_attr["res"]
    str_attr = getattr(value, "str", None)
    if isinstance(str_attr, dict) and isinstance(str_attr.get("res"), dict):
        return str_attr["res"]
    try:
        return dict(value)
    except Exception:
        return {}


def _coerce_bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        if all(key in value for key in ("x0", "y0", "x1", "y1")):
            return [float(value["x0"]), float(value["y0"]), float(value["x1"]), float(value["y1"])]
        if "bbox" in value:
            return _coerce_bbox(value.get("bbox"))
    if isinstance(value, (list, tuple)) and len(value) >= 4 and all(_looks_number(item) for item in value[:4]):
        x0, y0, x1, y1 = [float(item) for item in value[:4]]
        return [round(min(x0, x1), 2), round(min(y0, y1), 2), round(max(x0, x1), 2), round(max(y0, y1), 2)]
    points = _coerce_polygon(value)
    return _bbox_from_points(points) if points else None


def _coerce_polygon(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return None
    points = []
    for point in value:
        if hasattr(point, "tolist"):
            point = point.tolist()
        if isinstance(point, (list, tuple)) and len(point) >= 2 and _looks_number(point[0]) and _looks_number(point[1]):
            points.append([round(float(point[0]), 2), round(float(point[1]), 2)])
    return points or None


def _bbox_from_points(points: list[list[float]] | None) -> list[float] | None:
    if not points:
        return None
    return [round(min(p[0] for p in points), 2), round(min(p[1] for p in points), 2), round(max(p[0] for p in points), 2), round(max(p[1] for p in points), 2)]


def _merge_boxes(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [round(min(b[0] for b in boxes), 2), round(min(b[1] for b in boxes), 2), round(max(b[2] for b in boxes), 2), round(max(b[3] for b in boxes), 2)]


def _copy_geometry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_number": item.get("page_number") or item.get("page") or 1,
        "bbox": item.get("bbox"),
        "polygon": item.get("polygon"),
        "coordinate_space": item.get("coordinate_space") or COORDINATE_SPACE,
        "source": SOURCE,
        "confidence": item.get("confidence"),
        "source_width": item.get("source_width"),
        "source_height": item.get("source_height"),
    }


def _normalize_key_list(key_list: list[str] | None, document_type_hint: str | None) -> list[str]:
    keys = [str(item).strip() for item in (key_list or []) if str(item).strip()]
    if not keys:
        keys = list(DEFAULT_KEY_LIST)
    return list(dict.fromkeys(keys))


def _find_evidence_ref(value: str, evidence_lines: list[dict[str, Any]]) -> str | None:
    wanted = _norm(value)
    for item in evidence_lines:
        if wanted and wanted in _norm(item.get("text_preview")):
            return item.get("evidence_line_id")
    return evidence_lines[0].get("evidence_line_id") if evidence_lines else None


def _field_id(label: str, value: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "field"
    digest = hashlib.sha1(f"{label}:{value}:{index}".encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}"


def _category_for_label(label: str) -> str:
    lower = label.lower()
    if any(token in lower for token in ("name", "holder", "candidate", "student")):
        return "personal_name"
    if any(token in lower for token in ("issuer", "institution", "organization", "authority", "university", "school")):
        return "institution"
    if any(token in lower for token in ("credential", "degree", "certificate", "license", "course")):
        return "credential_title"
    if "date" in lower or "dob" in lower:
        return "date"
    if any(token in lower for token in ("id", "number", "roll", "registration")):
        return "identifier"
    if any(token in lower for token in ("grade", "score", "cgpa", "result")):
        return "score"
    if any(token in lower for token in ("email", "phone", "mobile")):
        return "contact"
    return "other"


def _sanitize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:120]


def _sanitize_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:300]


def _sanitize_preview(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:160]


def _mask_value(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 4:
        return f"****{digits[-4:]}"
    words = value.split()
    if len(words) >= 2 and all(re.match(r"^[A-Za-z][A-Za-z.'-]*$", word) for word in words[:3]):
        return " ".join(f"{word[0]}***" for word in words)
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _is_unresolved_value(value: str) -> bool:
    return _norm(value) in UNRESOLVED_VALUES or _norm(value).startswith("error:")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _average_confidence(items: list[dict[str, Any]]) -> float | None:
    values = [_coerce_float(item.get("confidence"), None) for item in items]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return None


def _safe_error(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:300]


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value if isinstance(value, list) else []


def _index_or_none(items: list[Any], index: int) -> Any:
    return items[index] if 0 <= index < len(items) else None


def _coerce_int(value: Any, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float | None) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _looks_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
