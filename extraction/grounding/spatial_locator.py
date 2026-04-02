import fitz
from typing import List
from extraction.schema.models import BoundingBox

def find_bounding_boxes(doc: fitz.Document, search_text: str) -> List[BoundingBox]:
    """
    Searches the PDF for the exact string and returns spatial coordinates for the frontend viewer.
    """
    bboxes = []
    
    # Clean the search text to avoid regex/newline breaks
    clean_text = " ".join(search_text.split())
    if not clean_text:
        return bboxes

    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # search_for returns a list of fitz.Rect objects
        text_instances = page.search_for(clean_text)
        
        for inst in text_instances:
            bboxes.append(BoundingBox(
                page=page_num + 1, # 1-indexed for frontend viewer
                x0=round(inst.x0, 2),
                y0=round(inst.y0, 2),
                x1=round(inst.x1, 2),
                y1=round(inst.y1, 2)
            ))
            
    return bboxes