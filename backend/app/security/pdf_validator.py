try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    from PyPDF2 import PdfReader  # type: ignore
import io


MAX_FILE_SIZE_MB = 25
MAX_PAGES = 200


class PDFValidationError(Exception):
    pass


def validate_pdf(file_bytes: bytes) -> None:
    """
    Main validation function.
    Raises PDFValidationError if invalid.
    """

    # 1. File size check
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise PDFValidationError("File too large")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        raise PDFValidationError("Malformed PDF")

    # 2. Page count check
    num_pages = len(reader.pages)
    if num_pages > MAX_PAGES:
        raise PDFValidationError("Too many pages")

    # 3. Encrypted PDF check
    if reader.is_encrypted:
        raise PDFValidationError("Encrypted PDFs not allowed")

    # 4. Check for JavaScript (basic check)
    if "/JavaScript" in str(reader.metadata):
        raise PDFValidationError("PDF contains JavaScript")

    # 5. Check for attachments (basic heuristic)
    for obj in reader.trailer.values():
        if isinstance(obj, dict) and "/EmbeddedFiles" in obj:
            raise PDFValidationError("PDF contains attachments")

    return
