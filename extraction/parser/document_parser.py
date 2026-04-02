import re
from typing import Dict

import fitz  # PyMuPDF

from extraction.grounding.spatial_locator import find_bounding_boxes
from extraction.ocr.engine import run_local_ocr_on_page
from extraction.schema.models import CanonicalSchema, ExtractedField, ExtractionResult


def extract_document_data(file_path: str) -> ExtractionResult:
    """
    Parse a PDF, fall back to OCR, normalize fields, and attach bounding boxes.
    """
    try:
        doc = fitz.open(file_path)

        if len(doc) > 200:
            raise ValueError("Document exceeds maximum 200-page limit.")

        full_text = ""
        used_ocr = False

        # 1. Primary extraction: attempt to use the PDF text layer.
        for page in doc:
            full_text += page.get_text()

        # 2. OCR fallback: treat low-text PDFs as scanned documents.
        if len(full_text.strip()) < 50:
            used_ocr = True
            full_text = ""
            for page in doc:
                full_text += run_local_ocr_on_page(page)

        # 3. Canonical normalization using dynamic regex rules.
        raw_extracted_dict = _apply_extraction_rules(full_text)

        # 4. Spatial grounding.
        schema = CanonicalSchema()
        for field_name, value in raw_extracted_dict.items():
            if not value:
                continue

            bboxes = find_bounding_boxes(doc, value)

            # Confidence is higher when we can ground the extracted value.
            confidence = 0.95 if bboxes else 0.60
            setattr(
                schema,
                field_name,
                ExtractedField(
                    value=value,
                    confidence=confidence,
                    bounding_boxes=bboxes,
                ),
            )

        return ExtractionResult(
            is_successful=True,
            used_ocr=used_ocr,
            fields=schema,
            raw_text=full_text,
        )

    except Exception as exc:
        return ExtractionResult(
            is_successful=False,
            used_ocr=False,
            fields=CanonicalSchema(),
            raw_text="",
            error_message=str(exc),
        )


def _apply_extraction_rules(text: str) -> Dict[str, str]:
    """
    Apply regex and string parsing to extract canonical fields from raw text.
    """
    extracted = {
        "candidate_name": "",
        "institution": "",
        "credential_type": "",
        "issue_date": "",
        "document_id": "",
    }

    # Clean up empty lines for easier parsing.
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if not lines:
        return extracted

    # 1. Candidate name: usually the first prominent line on the document.
    extracted["candidate_name"] = lines[0]

    # 2. Institution: look for expected university naming conventions.
    inst_match = re.search(
        (
            r"([A-Za-z.' ]*Vishwakarma Institute of Technology[A-Za-z, ]*|"
            r"[A-Za-z.' ]*Vellore Institute of Technology[A-Za-z, ]*|"
            r"VIT[A-Za-z, ]*)"
        ),
        text,
        re.IGNORECASE,
    )
    if inst_match:
        extracted["institution"] = inst_match.group(1).strip(", \n")

    # 3. Credential type: look for common degree names.
    cred_match = re.search(
        r"(Bachelor of Technology|B\.Tech|Bachelor of Engineering|B\.E\.|Master of Technology|M\.Tech)",
        text,
        re.IGNORECASE,
    )
    if cred_match:
        extracted["credential_type"] = cred_match.group(1).strip()

    # 4. Issue date / duration: look for a standard date span.
    date_match = re.search(
        r"([A-Z][a-z]{2,8}\s+\d{4}\s*-\s*(?:Present|\d{4}))",
        text,
        re.IGNORECASE,
    )
    if date_match:
        extracted["issue_date"] = date_match.group(1).strip()

    # 5. Document ID: first try a roll-number style token, then a phone number fallback.
    id_match = re.search(r"\b([A-Z0-9]{10,12})\b", text)
    if not id_match:
        id_match = re.search(r"\b(\d{10})\b", text)

    if id_match:
        extracted["document_id"] = id_match.group(1).strip()

    return extracted
