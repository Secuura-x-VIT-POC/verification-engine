import io

import fitz  # PyMuPDF
import pytesseract
from PIL import Image


def run_local_ocr_on_page(page: fitz.Page, dpi: int = 300) -> str:
    """
    Renders a PDF page to a high-res image and runs local Tesseract OCR.
    """
    # Convert the PyMuPDF page to an image pixmap.
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_bytes))

    # Extract text using local pytesseract.
    return pytesseract.image_to_string(img)
