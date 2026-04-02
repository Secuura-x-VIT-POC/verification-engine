from pydantic import BaseModel
from typing import List, Optional

class BoundingBox(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

class ExtractedField(BaseModel):
    value: str
    confidence: float
    bounding_boxes: List[BoundingBox]

class CanonicalSchema(BaseModel):
    candidate_name: Optional[ExtractedField] = None
    institution: Optional[ExtractedField] = None
    credential_type: Optional[ExtractedField] = None
    issue_date: Optional[ExtractedField] = None
    document_id: Optional[ExtractedField] = None

class ExtractionResult(BaseModel):
    is_successful: bool
    used_ocr: bool
    fields: CanonicalSchema
    raw_text: str
    error_message: Optional[str] = None