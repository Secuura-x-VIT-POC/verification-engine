import io
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    b"/RichMedia",
    b"/XFA",
    b"/AcroForm",
)
PDF_ACTIVE_CONTENT_STRIPPED_NOTICE = "PDF_ACTIVE_CONTENT_STRIPPED_FOR_SAFE_OCR"
DEFAULT_FLATTEN_DPI = 160

class PDFValidationError(Exception):
    pass

@dataclass(frozen=True)
class PDFValidationReport:
    file_size_bytes: int
    page_count: int | None = None
    encrypted: bool = False
    reason_code: str = "PDF_VALID"
    dangerous_markers: list[str] = field(default_factory=list)

    @property
    def has_active_or_embedded_content(self) -> bool:
        return bool(self.dangerous_markers) or self.reason_code in {
            "PDF_ACTIVE_CONTENT_DETECTED",
            "PDF_EMBEDDED_FILES_DETECTED",
            "PDF_JAVASCRIPT_DETECTED",
        }

@dataclass(frozen=True)
class PDFSafeCopyResult:
    safe_pdf_bytes: bytes
    original_report: PDFValidationReport
    safe_report: PDFValidationReport
    notice_code: str = PDF_ACTIVE_CONTENT_STRIPPED_NOTICE

def validate_pdf_upload_metadata(filename: str | None, content_type: str | None) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise PDFValidationError("Only PDF files are allowed")
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_content_type and normalized_content_type not in ALLOWED_PDF_MIME_TYPES:
        raise PDFValidationError("Only PDF content types are allowed")

def validate_pdf(file_bytes: bytes) -> None:
    validate_pdf_report(file_bytes)

def validate_pdf_report(file_bytes: bytes, *, allow_active_content: bool = False) -> PDFValidationReport:
    if not file_bytes:
        raise PDFValidationError("Empty PDF file")
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise PDFValidationError("File too large")
    if not file_bytes.lstrip().startswith(b"%PDF-"):
        raise PDFValidationError("Invalid PDF file signature")

    dangerous_markers = _find_dangerous_markers(file_bytes)
    if dangerous_markers and not allow_active_content:
        raise PDFValidationError("PDF contains active or embedded content")

    if PdfReader is None:  # pragma: no cover
        raise PDFValidationError("PDF parser dependency is not available")
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        raise PDFValidationError("Malformed PDF") from exc

    num_pages = len(reader.pages)
    if num_pages > MAX_PAGES:
        raise PDFValidationError("Too many pages")
    if reader.is_encrypted:
        raise PDFValidationError("Encrypted PDFs not allowed")

    try:
        metadata_text = str(reader.metadata or "")
    except Exception:
        metadata_text = ""
    if "/JavaScript" in metadata_text:
        if not allow_active_content:
            raise PDFValidationError("PDF contains JavaScript")
        dangerous_markers = sorted(set(dangerous_markers + ["/JavaScript"]))

    if _reader_contains_embedded_files(reader):
        if not allow_active_content:
            raise PDFValidationError("PDF contains attachments")
        dangerous_markers = sorted(set(dangerous_markers + ["/EmbeddedFiles"]))

    return PDFValidationReport(
        file_size_bytes=len(file_bytes),
        page_count=num_pages,
        encrypted=False,
        reason_code="PDF_ACTIVE_CONTENT_DETECTED" if dangerous_markers else "PDF_VALID",
        dangerous_markers=list(dangerous_markers),
    )

def safe_pdf_flattening_enabled() -> bool:
    return os.getenv("PDF_SAFE_FLATTEN_ACTIVE_CONTENT", "true").strip().lower() in {"1", "true", "yes", "on"}

def make_image_only_pdf(file_bytes: bytes, *, dpi: int | None = None) -> PDFSafeCopyResult:
    original_report = validate_pdf_report(file_bytes, allow_active_content=True)
    if not original_report.has_active_or_embedded_content:
        return PDFSafeCopyResult(
            safe_pdf_bytes=file_bytes,
            original_report=original_report,
            safe_report=original_report,
            notice_code="PDF_SAFE_FLATTEN_NOT_REQUIRED",
        )
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        raise PDFValidationError("PDF safe flattening dependency is not available") from exc

    flatten_dpi = max(72, min(dpi or _safe_int_env("PDF_SAFE_FLATTEN_DPI", DEFAULT_FLATTEN_DPI), 240))
    zoom = flatten_dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    try:
        src = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise PDFValidationError("Malformed PDF") from exc
    out = fitz.open()
    try:
        for page in src:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            width_pt = pix.width * 72.0 / flatten_dpi
            height_pt = pix.height * 72.0 / flatten_dpi
            safe_page = out.new_page(width=width_pt, height=height_pt)
            safe_page.insert_image(fitz.Rect(0, 0, width_pt, height_pt), stream=pix.tobytes("png"))
        safe_pdf_bytes = out.tobytes(garbage=4, deflate=True, clean=True)
    except Exception as exc:
        raise PDFValidationError("Could not create safe image-only PDF") from exc
    finally:
        out.close()
        src.close()
    safe_report = validate_pdf_report(safe_pdf_bytes, allow_active_content=False)
    return PDFSafeCopyResult(safe_pdf_bytes=safe_pdf_bytes, original_report=original_report, safe_report=safe_report)

def report_to_safe_dict(report: PDFValidationReport) -> dict:
    return asdict(report)

def write_pdf_security_sidecar(pdf_path: str | Path, payload: dict) -> None:
    Path(f"{pdf_path}.security.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

def read_pdf_security_sidecar(pdf_path: str | Path) -> dict:
    sidecar_path = Path(f"{pdf_path}.security.json")
    if not sidecar_path.exists():
        return {}
    try:
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _safe_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def _find_dangerous_markers(file_bytes: bytes) -> list[str]:
    scan_window = file_bytes[: min(len(file_bytes), 2 * 1024 * 1024)]
    return [marker.decode("ascii", errors="ignore") for marker in DANGEROUS_PDF_MARKERS if marker in scan_window]

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
