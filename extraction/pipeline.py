from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any

from .evidence_graph import build_evidence_graph_from_pp_chatocr
from .models import (
    BoundingBox,
    EvidenceLine,
    ExtractionResult,
    ExtractionWarning,
    FieldCandidate,
    OCRMetadata,
    SpatialTextToken,
)
from .ocr.pp_chatocr_v4 import (
    PPChatOCRConfigurationError,
    PPChatOCRExtractionError,
    run_pp_chatocr_v4_extraction,
)
from .output_builder import (
    build_canonical_schema,
    build_credential_candidates,
    build_document_metadata,
    build_generalized_analysis,
    build_processing_result,
    build_workspace_view,
)
from .pii_classifier import apply_verifier_feedback, classify_pii
from .security_gate import DocumentSafetyError, validate_document_intake

LOGGER = logging.getLogger(__name__)
INTERNAL_ONLY_WARNING_CODES = {"PP_CHATOCR_CHAT_STAGE_DISABLED", "PP_CHAT_OCR_CHAT_STAGE_DISABLED"}


def run_extraction(session_id: str, pdf_path: str, llm_client=None, strategy: str = "auto"):
    bundle = _run_extraction_bundle(session_id, pdf_path, llm_client=llm_client, strategy=strategy)
    return bundle["processing_result"], bundle["workspace_view"]


def run_extraction_with_feedback(
    session_id: str,
    pdf_path: str,
    verifier_mismatches: list[str],
    llm_client=None,
    strategy: str = "auto",
):
    bundle = _run_extraction_bundle(session_id, pdf_path, llm_client=llm_client, strategy=strategy)
    updated_candidates = apply_verifier_feedback(bundle["processing_result"].field_candidates, verifier_mismatches)
    processing_result = bundle["processing_result"].model_copy(update={"field_candidates": updated_candidates})
    workspace_view = build_workspace_view(processing_result)
    return processing_result, workspace_view


def extract_document_data(file_path: str) -> ExtractionResult:
    return extract_document_data_with_strategy(file_path, strategy="auto")


def extract_document_data_with_strategy(file_path: str, strategy: str = "auto") -> ExtractionResult:
    session_id = f"phase3_{hashlib.sha1(str(file_path).encode('utf-8')).hexdigest()[:10]}"
    try:
        bundle = _run_extraction_bundle(session_id, file_path, strategy=strategy)
    except DocumentSafetyError as exc:
        path = Path(file_path)
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            raw_text="",
            safety_report=exc.safety_report,
            warnings=[],
            reason_code=exc.reason_code,
            error_message=exc.message,
            metadata=None if not path.exists() else None,
        )
    except Exception as exc:
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            raw_text="",
            warnings=[ExtractionWarning(code="UNEXPECTED_PIPELINE_ERROR", message=str(exc))],
            reason_code="UNEXPECTED_PIPELINE_ERROR",
            error_message=str(exc),
        )

    return ExtractionResult(
        is_successful=True,
        used_ocr=bundle["processing_result"].ocr_metadata.ocr_applied,
        fields=bundle["canonical_schema"],
        raw_text="",
        raw_text_per_page=bundle["processing_result"].raw_text_per_page,
        spatial_text_map=bundle["spatial_text_map"],
        evidence_lines=bundle["evidence_lines"],
        field_candidates=bundle["processing_result"].field_candidates,
        generalized_analysis=bundle["generalized_analysis"],
        metadata=bundle["metadata"],
        ocr_metadata=bundle["processing_result"].ocr_metadata,
        safety_report=bundle["safety_report"],
        warnings=bundle["warnings"],
        processing_result=bundle["processing_result"],
        workspace_view=bundle["workspace_view"],
        extraction_method="pp_chatocr_v4",
        ocr_performed=True,
        advanced_ocr_performed=True,
        layout_blocks=bundle["layout_blocks"],
        table_cells=bundle["table_cells"],
        page_count=bundle["processing_result"].page_count,
        field_count=len(bundle["processing_result"].field_candidates),
        engine_metadata=bundle["engine_metadata"],
        evidence_graph=bundle["evidence_graph"],
    )


def _run_extraction_bundle(session_id: str, pdf_path: str, llm_client=None, strategy: str = "auto") -> dict:
    del llm_client, strategy
    started = time.perf_counter()
    path = Path(pdf_path)
    try:
        safety_report = validate_document_intake(str(path))
        document_type_hint = "generic"
        pp_payload = run_pp_chatocr_v4_extraction(str(path), document_type_hint=document_type_hint)
        evidence_graph = build_evidence_graph_from_pp_chatocr(pp_payload)
        warnings = [warning for warning in (_warning_from_payload(item) for item in list(pp_payload.get("warnings") or [])) if warning is not None]
        spatial_text_map = [_spatial_token_from_payload(item) for item in list(pp_payload.get("spatial_text_map") or [])]
        evidence_lines = [_evidence_line_from_payload(item) for item in list(pp_payload.get("evidence_lines") or [])]
        candidates = [_candidate_from_payload(item) for item in list(pp_payload.get("field_candidates") or [])]
        sanitized_candidates = [classify_pii(candidate) for candidate in candidates]
        credential_candidates = build_credential_candidates(sanitized_candidates, document_type_hint)
        ocr_metadata = OCRMetadata.model_validate(_coerce_ocr_metadata(pp_payload.get("ocr_metadata") or {}, page_count=int(pp_payload.get("page_count") or 0)))
        processing_result = build_processing_result(
            session_id=session_id,
            candidates=sanitized_candidates,
            credential_candidates=credential_candidates,
            ocr_metadata=ocr_metadata,
            raw_text_per_page={page: "" for page in range(1, int(pp_payload.get("page_count") or 1) + 1)},
            document_type_hint=document_type_hint,
        )
        workspace_view = build_workspace_view(processing_result)
        generalized_analysis = build_generalized_analysis(processing_result)
        canonical_schema = build_canonical_schema(processing_result.field_candidates)
        metadata = build_document_metadata(
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            size_bytes=path.stat().st_size,
            processing_result=processing_result,
            safety_report=safety_report,
        )
        return {
            "processing_result": processing_result,
            "workspace_view": workspace_view,
            "generalized_analysis": generalized_analysis,
            "canonical_schema": canonical_schema,
            "metadata": metadata,
            "safety_report": safety_report,
            "warnings": warnings,
            "spatial_text_map": spatial_text_map,
            "evidence_lines": evidence_lines,
            "layout_blocks": list(pp_payload.get("layout_blocks") or []),
            "table_cells": list(pp_payload.get("table_cells") or []),
            "engine_metadata": dict(pp_payload.get("engine_metadata") or {}),
            "evidence_graph": evidence_graph,
        }
    finally:
        LOGGER.info("extraction_total_ms=%d", int((time.perf_counter() - started) * 1000))


def _candidate_from_payload(item: dict) -> FieldCandidate:
    raw_boxes = list(item.get("bounding_boxes") or [])
    if isinstance(item.get("bounding_box"), dict):
        raw_boxes.append(item["bounding_box"])
    fallback_box = _box_from_bbox(item)
    if isinstance(fallback_box, dict):
        raw_boxes.append(fallback_box)
    boxes = _dedupe_boxes(raw_boxes)
    value = item.get("extracted_value") or item.get("normalized_value") or item.get("masked_value") or ""
    return FieldCandidate(
        field_id=str(item.get("field_id") or item.get("label") or "field"),
        label=str(item.get("label") or "Field"),
        raw_value=str(value),
        extracted_value=str(value),
        masked_value=item.get("masked_value"),
        normalized_value=str(item.get("normalized_value") or value),
        category=item.get("category") if item.get("category") in FieldCandidate.model_fields["category"].annotation.__args__ else "other",
        page=int(item.get("page_number") or item.get("page") or 1),
        page_number=int(item.get("page_number") or item.get("page") or 1),
        bbox=item.get("bbox"),
        polygon=item.get("polygon"),
        coordinate_space=item.get("coordinate_space"),
        source="pp_chatocr_v4",
        evidence_ref=item.get("evidence_ref"),
        evidence_line_id=item.get("evidence_line_id"),
        ocr_performed=True,
        advanced_ocr_performed=True,
        bounding_boxes=boxes,
        confidence=float(item.get("confidence") or 0.0),
        source_text=None,
        extraction_method="pp_chatocr_v4",
        detected_by=["layout"] if boxes else [],
        requires_verification=bool(item.get("requires_verification", True)),
    )


def _dedupe_boxes(raw_boxes: list[dict]) -> list[BoundingBox]:
    boxes: list[BoundingBox] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for raw_box in raw_boxes:
        if not isinstance(raw_box, dict) or not raw_box.get("bbox"):
            continue
        box = BoundingBox.model_validate(raw_box)
        key = (
            int(box.page_number or box.page or 1),
            round(float(box.x0), 2),
            round(float(box.y0), 2),
            round(float(box.x1), 2),
            round(float(box.y1), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        boxes.append(box)
    return boxes


def _warning_from_payload(item: Any) -> ExtractionWarning | None:
    code = "OCR_WARNING"
    message = "OCR warning"
    if hasattr(item, "model_dump"):
        try:
            item = item.model_dump(mode="json")
        except Exception:
            pass
    if isinstance(item, dict):
        code = _safe_warning_code(
            item.get("code")
            or item.get("warning_code")
            or item.get("reason_code")
            or item.get("type")
            or item.get("stage")
            or item.get("error_code")
            or item.get("message")
        )
        message = _safe_warning_message(item.get("message") or code)
    elif item not in (None, ""):
        code = _safe_warning_code(item)
        message = _safe_warning_message(item)
    if code in INTERNAL_ONLY_WARNING_CODES:
        return None
    return ExtractionWarning(code=code or "OCR_WARNING", message=message or "OCR warning")


def _safe_warning_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "OCR_WARNING"
    upper = text.upper()
    if any(marker in upper for marker in ("RAW", "SECRET", "PRIVATE", "PROMPT", "GEMINI_RESPONSE", "PROVIDER_RAW", "PROVIDER_BODY", "REVIEWER_NOTE")):
        return "OCR_WARNING_REDACTED"
    code = re.sub(r"[^A-Z0-9]+", "_", upper).strip("_")
    code = re.sub(r"_+", "_", code)
    if not code:
        return "OCR_WARNING"
    if len(code) > 96:
        return "OCR_WARNING_REDACTED"
    return code


def _safe_warning_message(value: Any) -> str:
    code = _safe_warning_code(value)
    if code.endswith("_REDACTED"):
        return "OCR warning redacted"
    return code.replace("_", " ").title()


def _spatial_token_from_payload(item: dict) -> SpatialTextToken:
    bbox = item.get("bbox") or [0, 0, 0, 0]
    return SpatialTextToken(
        text=str(item.get("text_preview") or item.get("text") or ""),
        bbox=[float(value) for value in bbox],
        page=int(item.get("page_number") or item.get("page") or 1),
        source="pp_chatocr_v4",
        confidence=float(item.get("confidence") or 0.0),
        polygon=item.get("polygon"),
    )


def _evidence_line_from_payload(item: dict) -> EvidenceLine:
    box = item.get("bbox") or [0, 0, 0, 0]
    page = int(item.get("page_number") or item.get("page") or 1)
    return EvidenceLine(
        page=page,
        text=str(item.get("text_preview") or ""),
        bbox=BoundingBox(
            page=page,
            x0=float(box[0]),
            y0=float(box[1]),
            x1=float(box[2]),
            y1=float(box[3]),
            page_number=page,
            bbox=[float(value) for value in box],
            polygon=item.get("polygon"),
            coordinate_space=item.get("coordinate_space"),
            source="pp_chatocr_v4",
            confidence=item.get("confidence"),
        ),
        source="pp_chatocr_v4",
    )


def _box_from_bbox(item: dict) -> dict | None:
    bbox = item.get("bbox")
    if not bbox:
        return None
    page = int(item.get("page_number") or item.get("page") or 1)
    return {
        "page": page,
        "page_number": page,
        "x0": float(bbox[0]),
        "y0": float(bbox[1]),
        "x1": float(bbox[2]),
        "y1": float(bbox[3]),
        "bbox": [float(value) for value in bbox],
        "polygon": item.get("polygon"),
        "coordinate_space": item.get("coordinate_space"),
        "source": "pp_chatocr_v4",
        "confidence": item.get("confidence"),
    }


def _coerce_ocr_metadata(payload: dict, *, page_count: int) -> dict:
    base = {
        "method_used": "pp_chatocr_v4",
        "fallback_triggered": False,
        "total_pages": page_count,
        "ocr_pages": list(range(1, page_count + 1)),
        "avg_confidence": payload.get("avg_confidence") or payload.get("average_confidence") or 0.0,
        "language_detected": None,
        "engine_used": "pp_chatocr_v4",
        "engines_used": ["pp_chatocr_v4"],
        "native_text_used": False,
        "ocr_applied": True,
        "fallback_used": False,
        "average_confidence": payload.get("average_confidence") or payload.get("avg_confidence"),
        "preprocessing_applied": [],
        "pages_ocrd": list(range(1, page_count + 1)),
        "page_metadata": [
            {
                "page": page,
                "engine": "pp_chatocr_v4",
                "used_native_text": False,
                "average_confidence": payload.get("average_confidence") or payload.get("avg_confidence"),
                "preprocessing_applied": [],
                "warning_codes": [],
            }
            for page in range(1, page_count + 1)
        ],
        "warning_codes": payload.get("warning_codes") or [],
    }
    base.update({key: value for key, value in payload.items() if key in base})
    return base


def _infer_document_type_hint(raw_text_per_page: dict[int, str]) -> str:
    raw_text = "\n".join(raw_text_per_page.values()).lower()
    if (
        any(token in raw_text for token in ("linkedin", "technical competencies", "skills", "projects", "summary"))
        and any(token in raw_text for token in ("internship", "experience", "resume", "curriculum vitae", "volunteer"))
    ):
        return "resume"
    if any(token in raw_text for token in ("transcript", "marksheet", "mark sheet", "report card", "cgpa", "semester")):
        return "academic_transcript"
    if any(token in raw_text for token in ("degree", "bachelor", "master", "awarded")):
        return "academic_degree"
    if any(token in raw_text for token in ("aadhaar", "pan", "passport", "date of birth")):
        return "identity_document"
    if any(token in raw_text for token in ("invoice", "gst", "amount due", "tax invoice")):
        return "invoice"
    if any(token in raw_text for token in ("license", "licence", "permit")):
        return "license"
    if any(token in raw_text for token in ("employment", "joining", "designation", "salary")):
        return "employment_letter"
    if any(token in raw_text for token in ("certificate", "completion", "certified")):
        return "certificate"
    if any(token in raw_text for token in ("bank", "statement", "account", "transaction")):
        return "financial_document"
    return "generic"
