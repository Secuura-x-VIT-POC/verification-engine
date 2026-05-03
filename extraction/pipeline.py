from __future__ import annotations

import hashlib
from pathlib import Path

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
    )


def _run_extraction_bundle(session_id: str, pdf_path: str, llm_client=None, strategy: str = "auto") -> dict:
    del llm_client, strategy
    path = Path(pdf_path)
    safety_report = validate_document_intake(str(path))
    document_type_hint = "generic"
    pp_payload = run_pp_chatocr_v4_extraction(str(path), document_type_hint=document_type_hint)
    warnings = [
        ExtractionWarning(code=str(code).upper(), message=str(code))
        for code in list(pp_payload.get("warnings") or [])
    ]
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
    }


def _candidate_from_payload(item: dict) -> FieldCandidate:
    bbox = item.get("bounding_box") or _box_from_bbox(item)
    boxes = [BoundingBox.model_validate(bbox)] if isinstance(bbox, dict) and bbox.get("bbox") else []
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
