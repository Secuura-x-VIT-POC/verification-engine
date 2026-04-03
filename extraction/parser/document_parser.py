import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List

from extraction.analysis import build_generalized_analysis
from extraction.schema.models import (
    CanonicalSchema,
    DocumentMetadata,
    ExtractedField,
    ExtractionResult,
    ExtractionWarning,
    SafetyReport,
    SpatialTextToken,
)
from extraction.security import DocumentSafetyError, validate_document_intake

MIN_TEXT_THRESHOLD = 50
SCANNED_CHARACTER_DENSITY_THRESHOLD = 8.0
SCANNED_WORD_COUNT_THRESHOLD = 20
PARSING_TIMEOUT_SECONDS = 20
OCR_TIMEOUT_SECONDS = 90


def extract_document_data(file_path: str) -> ExtractionResult:
    """
    Strict PDF extraction pipeline with safety validation, sandboxed parsing, private AI extraction, and grounding.
    """
    return extract_document_data_with_strategy(file_path, strategy="auto")


def extract_document_data_with_strategy(file_path: str, strategy: str = "auto") -> ExtractionResult:
    path = Path(file_path)
    metadata = DocumentMetadata(
        file_name=path.name,
        file_type=path.suffix.lower().lstrip("."),
        size_bytes=path.stat().st_size if path.exists() else 0,
    )
    warnings: List[ExtractionWarning] = []
    safety_report: SafetyReport | None = None

    try:
        safety_report = validate_document_intake(str(path))

        native_result = _run_sandbox_parse(path, mode="native", timeout_seconds=PARSING_TIMEOUT_SECONDS)
        native_character_density = float(native_result.get("character_density", 0.0))
        native_word_count = int(native_result.get("word_count", 0))
        native_raw_text = str(native_result.get("raw_text", "")).strip()
        is_scanned = _is_scanned_document(native_character_density, native_word_count, len(native_raw_text))
        native_text_insufficient = len(native_raw_text) < MIN_TEXT_THRESHOLD and native_word_count < SCANNED_WORD_COUNT_THRESHOLD

        selected_result = native_result
        used_ocr = False

        if strategy == "ocr_only":
            selected_result = _run_sandbox_parse(path, mode="ocr", timeout_seconds=OCR_TIMEOUT_SECONDS)
            used_ocr = True
            warnings.append(ExtractionWarning(code="FORCED_OCR", message="OCR-only strategy was used for this PDF."))
        elif strategy == "auto" and (is_scanned or native_text_insufficient):
            try:
                selected_result = _run_sandbox_parse(path, mode="hybrid", timeout_seconds=OCR_TIMEOUT_SECONDS)
                used_ocr = True
                warnings.append(ExtractionWarning(code="OCR_FALLBACK", message="Hybrid OCR fallback was used because the PDF appears scanned or text-sparse."))
            except RuntimeError as exc:
                if _is_tesseract_missing(str(exc)) and native_raw_text:
                    selected_result = native_result
                    warnings.append(
                        ExtractionWarning(
                            code="OCR_UNAVAILABLE_NATIVE_USED",
                            message="OCR fallback was unavailable on this machine, so the pipeline continued with native PDF text extraction.",
                        )
                    )
                else:
                    raise
        elif strategy == "text_only" and is_scanned:
            warnings.append(ExtractionWarning(code="SCANNED_TEXT_LAYER", message="Text-only mode was used on a document that appears scanned."))

        raw_text = _normalize_text(str(selected_result.get("raw_text", "")))
        spatial_text_map = []
        for token_data in selected_result.get("spatial_text_map", []):
            normalized_token_text = _normalize_token_text(token_data.get("text", ""))
            if not normalized_token_text:
                continue
            spatial_text_map.append(
                SpatialTextToken(
                    text=normalized_token_text,
                    bbox=token_data.get("bbox", []),
                    page=token_data.get("page", 0),
                    source=token_data.get("source", "native_text"),
                    confidence=float(token_data.get("confidence", 1.0)),
                )
            )

        extraction_method = strategy if strategy != "auto" else ("hybrid" if used_ocr else "native_text")
        evidence_lines, field_candidates, generalized_analysis = build_generalized_analysis(
            raw_text=raw_text,
            spatial_text_map=spatial_text_map,
            extraction_method=extraction_method,
            warnings=warnings,
        )
        fields = _build_canonical_schema(field_candidates)

        metadata.page_count = safety_report.page_count
        metadata.text_char_count = len(raw_text)
        metadata.extraction_method = extraction_method
        metadata.character_density = float(selected_result.get("character_density", native_character_density))
        metadata.min_resolution_dpi = safety_report.min_resolution_dpi
        metadata.is_scanned = is_scanned
        metadata.sandboxed_processing = True

        safety_report.character_density = metadata.character_density
        safety_report.is_scanned = is_scanned

        if not raw_text.strip():
            warnings.append(ExtractionWarning(code="EMPTY_TEXT", message="No extractable text was produced from the PDF."))

        return ExtractionResult(
            is_successful=True,
            used_ocr=used_ocr,
            fields=fields,
            raw_text=raw_text,
            spatial_text_map=spatial_text_map,
            evidence_lines=evidence_lines,
            field_candidates=field_candidates,
            generalized_analysis=generalized_analysis,
            metadata=metadata,
            safety_report=safety_report,
            warnings=warnings,
        )
    except DocumentSafetyError as exc:
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            fields=CanonicalSchema(),
            raw_text="",
            spatial_text_map=[],
            metadata=metadata,
            safety_report=exc.safety_report or safety_report,
            warnings=warnings,
            reason_code=exc.reason_code,
            error_message=exc.message,
        )
    except subprocess.TimeoutExpired as exc:
        reason_code = "OCR_TIMEOUT" if "ocr" in " ".join(exc.cmd).lower() else "PARSING_TIMEOUT"
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            fields=CanonicalSchema(),
            raw_text="",
            spatial_text_map=[],
            metadata=metadata,
            safety_report=safety_report,
            warnings=warnings,
            reason_code=reason_code,
            error_message=f"{reason_code.replace('_', ' ').title()} was exceeded.",
        )
    except RuntimeError as exc:
        reason_code = _reason_code_for_exception(str(exc), default="SANDBOX_PARSE_FAILED")
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            fields=CanonicalSchema(),
            raw_text="",
            spatial_text_map=[],
            evidence_lines=[],
            field_candidates=[],
            generalized_analysis=None,
            metadata=metadata,
            safety_report=safety_report,
            warnings=warnings,
            reason_code=reason_code,
            error_message=str(exc),
        )
    except Exception as exc:
        reason_code = _reason_code_for_exception(str(exc), default="UNEXPECTED_PIPELINE_ERROR")
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            fields=CanonicalSchema(),
            raw_text="",
            spatial_text_map=[],
            evidence_lines=[],
            field_candidates=[],
            generalized_analysis=None,
            metadata=metadata,
            safety_report=safety_report,
            warnings=warnings,
            reason_code=reason_code,
            error_message=str(exc),
        )


def _run_sandbox_parse(path: Path, mode: str, timeout_seconds: int) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "extraction.ocr.engine", mode, str(path)],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Sandbox worker failed."
        raise RuntimeError(stderr)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Sandbox worker returned invalid JSON: {exc}") from exc


def _is_scanned_document(character_density: float, word_count: int, text_char_count: int) -> bool:
    return (
        character_density < SCANNED_CHARACTER_DENSITY_THRESHOLD
        and word_count < SCANNED_WORD_COUNT_THRESHOLD
        and text_char_count < MIN_TEXT_THRESHOLD
    )


def _normalize_text(text: str) -> str:
    replacements = {
        "\uf0b7": "-",
        "\u2022": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\ufffd": " ",
        "â€™": "'",
        "â€œ": '"',
        "â€\x9d": '"',
        "â€“": "-",
        "â€”": "-",
        "ï¿½": "",
    }
    normalized = text.replace("\r", "\n")
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_token_text(text: str) -> str:
    normalized = _normalize_text(str(text))
    return normalized.replace("\n", " ").strip()


def _build_canonical_schema(field_candidates) -> CanonicalSchema:
    schema = CanonicalSchema()
    category_to_field = {
        "person_name": "candidate_name",
        "issuer": "institution",
        "credential_title": "credential_type",
        "issue_date": "issue_date",
        "date_reference": "issue_date",
        "registration_number": "document_id",
        "document_number": "document_id",
        "license_number": "document_id",
        "email": "email",
        "phone_number": "phone_number",
    }

    best_by_field = {}
    for candidate in field_candidates:
        target_field = category_to_field.get(candidate.category)
        if not target_field:
            continue
        current = best_by_field.get(target_field)
        if current is None or candidate.confidence > current.confidence:
            best_by_field[target_field] = candidate

    for field_name, candidate in best_by_field.items():
        setattr(
            schema,
            field_name,
            ExtractedField(
                value=candidate.raw_value,
                confidence=candidate.confidence,
                bounding_boxes=[candidate.bounding_box] if candidate.bounding_box else [],
                match_type=candidate.grounding_match_type,
            ),
        )
    return schema


def _reason_code_for_exception(message: str, default: str) -> str:
    lowered = message.lower()
    if _is_tesseract_missing(lowered):
        return "OCR_ENGINE_UNAVAILABLE"
    malformed_markers = (
        "malformed pdf",
        "multiple definitions in dictionary",
        "cannot open broken document",
        "repairing PDF",
        "format error",
        "syntax error",
        "xref",
    )
    if any(marker in lowered for marker in malformed_markers):
        return "MALFORMED_PDF"
    return default


def _is_tesseract_missing(message: str) -> bool:
    lowered = message.lower()
    return "tesseractnotfounderror" in lowered or "tesseract is not installed" in lowered
