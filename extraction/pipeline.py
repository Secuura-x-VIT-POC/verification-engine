from __future__ import annotations

import hashlib
from pathlib import Path

from .confidence_scorer import score_candidate
from .cross_field_validator import validate_cross_fields
from .deduplication import fuzzy_deduplicate
from .field_detector import extract_field_candidates
from .layout_analyzer import build_evidence_lines, extract_tables_from_lines
from .models import ExtractionResult, ExtractionWarning
from .output_builder import (
    build_canonical_schema,
    build_credential_candidates,
    build_document_metadata,
    build_generalized_analysis,
    build_processing_result,
    build_workspace_view,
)
from .pii_classifier import apply_verifier_feedback, classify_pii, redact_source_snippet
from .router import route_extraction
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

    raw_text = "\n".join(bundle["processing_result"].raw_text_per_page[page] for page in sorted(bundle["processing_result"].raw_text_per_page))
    return ExtractionResult(
        is_successful=True,
        used_ocr=bundle["processing_result"].ocr_metadata.ocr_applied,
        fields=bundle["canonical_schema"],
        raw_text=raw_text,
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
    )


def _run_extraction_bundle(session_id: str, pdf_path: str, llm_client=None, strategy: str = "auto") -> dict:
    path = Path(pdf_path)
    safety_report = validate_document_intake(str(path))
    warnings: list[ExtractionWarning] = []
    routed = route_extraction(str(path), strategy=strategy)
    evidence_lines = build_evidence_lines(routed.spatial_tokens)
    merged_tables = dict(routed.tables_by_page)
    heuristic_tables = extract_tables_from_lines(evidence_lines)
    for page, tables in heuristic_tables.items():
        merged_tables.setdefault(page, [])
        merged_tables[page].extend(tables)

    document_type_hint = _infer_document_type_hint(routed.page_texts)
    candidates = extract_field_candidates(
        raw_text_per_page=routed.page_texts,
        evidence_lines=evidence_lines,
        spatial_text_map=routed.spatial_tokens,
        page_confidence=routed.page_confidence,
        page_methods=routed.page_methods,
        tables_by_page=merged_tables,
        document_type_hint=document_type_hint,
        llm_client=llm_client,
    )
    candidates = [score_candidate(classify_pii(candidate)) for candidate in candidates]
    candidates = validate_cross_fields(candidates)
    candidates = fuzzy_deduplicate(candidates)
    sanitized_candidates = []
    for candidate in candidates:
        sanitized_candidates.append(
            candidate.model_copy(
                update={
                    "source_text": redact_source_snippet(candidate.source_text, candidate.raw_value, candidate.sensitivity),
                }
            )
        )
    credential_candidates = build_credential_candidates(sanitized_candidates, document_type_hint)
    processing_result = build_processing_result(
        session_id=session_id,
        candidates=sanitized_candidates,
        credential_candidates=credential_candidates,
        ocr_metadata=routed.ocr_metadata,
        raw_text_per_page=routed.page_texts,
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
        "spatial_text_map": routed.spatial_tokens,
        "evidence_lines": evidence_lines,
    }


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
