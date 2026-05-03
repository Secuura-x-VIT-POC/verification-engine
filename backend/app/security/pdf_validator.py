import io
from dataclasses import dataclass, field

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError:  # pragma: no cover
        PdfReader = None  # type: ignore


MAX_FILE_SIZE_MB = 25
MAX_PAGES = 200
ALLOWED_PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
DANGEROUS_PDF_MARKERS = (
    b"/JavaScript",
    b"/JS",
    b"/OpenAction",
    b"/AA",
    b"/Launch",
    b"/EmbeddedFile",
    b"/EmbeddedFiles",
)


class PDFValidationError(Exception):
    pass


@dataclass(frozen=True)
class PDFValidationReport:
    file_size_bytes: int
    page_count: int | None = None
    encrypted: bool = False
    reason_code: str = "PDF_VALID"
    dangerous_markers: list[str] = field(default_factory=list)


def validate_pdf_upload_metadata(filename: str | None, content_type: str | None) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise PDFValidationError("Only PDF files are allowed")

    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_content_type and normalized_content_type not in ALLOWED_PDF_MIME_TYPES:
        raise PDFValidationError("Only PDF content types are allowed")


def validate_pdf(file_bytes: bytes) -> None:
    """
    Main validation function.
    Raises PDFValidationError if invalid.
    """
    validate_pdf_report(file_bytes)


def validate_pdf_report(file_bytes: bytes) -> PDFValidationReport:
    if not file_bytes:
        raise PDFValidationError("Empty PDF file")

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise PDFValidationError("File too large")

    if not file_bytes.lstrip().startswith(b"%PDF-"):
        raise PDFValidationError("Invalid PDF file signature")

    dangerous_markers = _find_dangerous_markers(file_bytes)
    if dangerous_markers:
        raise PDFValidationError("PDF contains active or embedded content")

    if PdfReader is None:  # pragma: no cover - exercised only without installed PDF parser
        raise PDFValidationError("PDF parser dependency is not available")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        raise PDFValidationError("Malformed PDF")

    num_pages = len(reader.pages)
    if num_pages > MAX_PAGES:
        raise PDFValidationError("Too many pages")

    if reader.is_encrypted:
        raise PDFValidationError("Encrypted PDFs not allowed")

    if "/JavaScript" in str(reader.metadata):
        raise PDFValidationError("PDF contains JavaScript")

    if _reader_contains_embedded_files(reader):
        raise PDFValidationError("PDF contains attachments")

    return PDFValidationReport(
        file_size_bytes=len(file_bytes),
        page_count=num_pages,
        encrypted=False,
        dangerous_markers=[],
    )


def _find_dangerous_markers(file_bytes: bytes) -> list[str]:
    scan_window = file_bytes[: min(len(file_bytes), 2 * 1024 * 1024)]
    return [
        marker.decode("ascii", errors="ignore")
        for marker in DANGEROUS_PDF_MARKERS
        if marker in scan_window
    ]


def _reader_contains_embedded_files(reader) -> bool:
    try:
        trailer = reader.trailer
    except Exception:
        return False

    return _contains_pdf_key(trailer, "/EmbeddedFiles") or _contains_pdf_key(trailer, "/EmbeddedFile")


def _contains_pdf_key(value, target_key: str, *, depth: int = 0) -> bool:
    if depth > 8:
        return False
    try:
        if hasattr(value, "get_object"):
            value = value.get_object()
    except Exception:
        return False

    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) == target_key:
                return True
            if _contains_pdf_key(nested, target_key, depth=depth + 1):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_pdf_key(item, target_key, depth=depth + 1) for item in value)
    return False
