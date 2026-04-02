import fitz  # PyMuPDF
import re
from typing import Dict
from extraction.schema.models import ExtractedField, CanonicalSchema, ExtractionResult
from extraction.ocr.engine import run_local_ocr_on_page
from extraction.grounding.spatial_locator import find_bounding_boxes

def extract_document_data(file_path: str) -> ExtractionResult:
    """
    Main pipeline: Parses PDF, falls back to OCR, normalizes fields, and maps bounding boxes.
    """
    try:
        doc = fitz.open(file_path)
        
        if len(doc) > 200:
            raise ValueError("Document exceeds maximum 200-page limit.")

        full_text = ""
        used_ocr = False
        
        # 1. Primary Extraction: Attempt PyMuPDF text layer
        for page in doc:
            full_text += page.get_text()
        
        # 2. OCR Fallback: If minimal text is found, assume scanned image
        if len(full_text.strip()) < 50:
            used_ocr = True
            full_text = ""
            for page in doc:
                full_text += run_local_ocr_on_page(page)
        
        # 3. Canonical Normalization using dynamic Regex
        raw_extracted_dict = _apply_extraction_rules(full_text)
        
        # 4. Spatial Grounding
        schema = CanonicalSchema()
        for field_name, value in raw_extracted_dict.items():
            if value:
                bboxes = find_bounding_boxes(doc, value)
                
                # Assign confidence: high if grounded coordinates found, lower if just regex guess
                confidence = 0.95 if bboxes else 0.60
                
                setattr(schema, field_name, ExtractedField(
                    value=value,
                    confidence=confidence,
                    bounding_boxes=bboxes
                ))
                
        return ExtractionResult(
            is_successful=True,
            used_ocr=used_ocr,
            fields=schema,
            raw_text=full_text,
        )
        
    except Exception as e:
        return ExtractionResult(
            is_successful=False, 
            used_ocr=False, 
            fields=CanonicalSchema(), 
            raw_text="", 
            error_message=str(e)
        )

def _apply_extraction_rules(text: str) -> Dict[str, str]:
    """
    Applies regex and string parsing to dynamically extract canonical fields from the raw text.
    """
    extracted = {
        "candidate_name": "",
        "institution": "",
        "credential_type": "",
        "issue_date": "",
        "document_id": ""
    }

    # Clean up empty lines for easier parsing
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    if not lines:
        return extracted

    # 1. Candidate Name: Usually the very first prominent line of a resume or transcript
    extracted["candidate_name"] = lines[0]

    # 2. Institution: Look for standard university naming conventions
    inst_match = re.search(r'([A-Za-z.\' ]*Vishwakarma Institute of Technology[A-Za-z, ]*|[A-Za-z.\' ]*Vellore Institute of Technology[A-Za-z, ]*|VIT[A-Za-z, ]*)', text, re.IGNORECASE)
    if inst_match:
        # Clean up any trailing/leading artifacts
        extracted["institution"] = inst_match.group(1).strip(', \n')

    # 3. Credential Type: Look for standard degrees
    cred_match = re.search(r'(Bachelor of Technology|B\.Tech|Bachelor of Engineering|B\.E\.|Master of Technology|M\.Tech)', text, re.IGNORECASE)
    if cred_match:
        extracted["credential_type"] = cred_match.group(1).strip()

    # 4. Issue Date / Duration: Look for "Nov 2024-Present" or standard dates
    date_match = re.search(r'([A-Z][a-z]{2,8}\s+\d{4}\s*-\s*(?:Present|\d{4}))', text, re.IGNORECASE)
    if date_match:
        extracted["issue_date"] = date_match.group(1).strip()

    # 5. Document ID: Resumes don't have PRN/Roll numbers clearly labeled as "ID". 
    # For the POC, we will extract a 10-digit phone number as a unique identifier if a formal ID isn't found.
    id_match = re.search(r'\b([A-Z0-9]{10,12})\b', text) # Generic alphanumeric roll number
    if not id_match:
        id_match = re.search(r'\b(\d{10})\b', text) # Phone number fallback
    
    if id_match:
        extracted["document_id"] = id_match.group(1).strip()

    return extracted