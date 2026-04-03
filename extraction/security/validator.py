from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import fitz  # PyMuPDF

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject
except ImportError:  # pragma: no cover - dependency fallback
    from PyPDF2 import PdfReader  # type: ignore
    from PyPDF2.errors import PdfReadError  # type: ignore
    from PyPDF2.generic import ArrayObject, DictionaryObject, IndirectObject  # type: ignore

from extraction.schema.models import SafetyReport

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
MAX_PAGE_LIMIT = 200
MIN_RESOLUTION_DPI = 150.0
MALWARE_SCAN_TIMEOUT_SECONDS = 30
DEFAULT_TEXT_PAGE_DPI = 300.0

BLOCKLIST_PATH = Path(__file__).resolve().parent / "malware_hash_blocklist.json"


class DocumentSafetyError(Exception):
    def __init__(self, reason_code: str, message: str, safety_report: Optional[SafetyReport] = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.safety_report = safety_report


def validate_document_intake(file_path: str) -> SafetyReport:
    path = Path(file_path)
    if path.suffix.lower() != ".pdf":
        raise DocumentSafetyError("UNSUPPORTED_FORMAT", "Only PDF documents are accepted for extraction.")
    if not path.exists():
        raise DocumentSafetyError("FILE_NOT_FOUND", "Input document was not found.")

    file_size = path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise DocumentSafetyError("FILE_TOO_LARGE", "PDF exceeds the 25 MB size limit.")

    malware_engine, malware_passed = _scan_for_malware(path)
    safety_report = SafetyReport(
        sandboxed=True,
        malware_scan_engine=malware_engine,
        malware_scan_passed=malware_passed,
        file_size_bytes=file_size,
    )
    if not malware_passed:
        raise DocumentSafetyError("MALWARE_DETECTED", "Malware scan failed for the uploaded PDF.", safety_report)

    try:
        reader = PdfReader(str(path), strict=True)
        page_count = len(reader.pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise DocumentSafetyError("MALFORMED_PDF", f"Malformed PDF rejected: {exc}", safety_report) from exc

    safety_report.page_count = page_count
    if getattr(reader, "is_encrypted", False):
        raise DocumentSafetyError("PASSWORD_PROTECTED", "Password-protected PDFs are not allowed.", safety_report)
    if page_count > MAX_PAGE_LIMIT:
        raise DocumentSafetyError("PAGE_LIMIT_EXCEEDED", "PDF exceeds the 200-page limit.", safety_report)

    blocked_reason = _find_blocked_pdf_content(reader)
    if blocked_reason is not None:
        raise DocumentSafetyError(blocked_reason, "PDF contains blocked active content or attachments.", safety_report)

    min_resolution_dpi = _estimate_minimum_resolution(path)
    safety_report.min_resolution_dpi = min_resolution_dpi
    if min_resolution_dpi < MIN_RESOLUTION_DPI:
        raise DocumentSafetyError("LOW_RESOLUTION", "PDF resolution is below the required 150 DPI minimum.", safety_report)

    return safety_report


def _scan_for_malware(path: Path) -> tuple[str, bool]:
    clamscan_path = shutil.which("clamscan")
    if clamscan_path:
        completed = subprocess.run(
            [clamscan_path, "--no-summary", str(path)],
            capture_output=True,
            text=True,
            timeout=MALWARE_SCAN_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode == 0:
            return "clamav", True
        if completed.returncode == 1:
            return "clamav", False
        raise DocumentSafetyError("MALWARE_SCAN_FAILED", completed.stderr.strip() or "ClamAV scan failed.")

    blocked_hashes = _load_blocked_hashes()
    return "sha256_blocklist", _sha256(path) not in blocked_hashes


def _load_blocked_hashes() -> set[str]:
    if not BLOCKLIST_PATH.exists():
        return set()
    try:
        payload = json.loads(BLOCKLIST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {str(item).lower() for item in payload.get("blocked_sha256", [])}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _find_blocked_pdf_content(reader: PdfReader) -> Optional[str]:
    visited: set[int] = set()
    return _walk_pdf_object(reader.trailer, visited)


def _walk_pdf_object(obj: Any, visited: set[int]) -> Optional[str]:
    if isinstance(obj, IndirectObject):
        obj = obj.get_object()

    object_id = id(obj)
    if object_id in visited:
        return None
    visited.add(object_id)

    if isinstance(obj, DictionaryObject):
        for key, value in obj.items():
            key_name = str(key)
            if key_name in {"/JS", "/JavaScript"}:
                return "EMBEDDED_JAVASCRIPT_BLOCKED"
            if key_name == "/EmbeddedFiles":
                return "ATTACHMENT_BLOCKED"
            if key_name == "/Subtype" and str(value) == "/FileAttachment":
                return "ATTACHMENT_BLOCKED"
            if key_name == "/Type" and str(value) == "/Filespec" and ("/EF" in obj or "/F" in obj or "/UF" in obj):
                return "ATTACHMENT_BLOCKED"
            if key_name == "/S" and str(value) == "/Launch":
                return "LAUNCH_ACTION_BLOCKED"
            if key_name == "/S" and str(value) == "/JavaScript":
                return "EMBEDDED_JAVASCRIPT_BLOCKED"
            nested = _walk_pdf_object(value, visited)
            if nested is not None:
                return nested

    if isinstance(obj, ArrayObject):
        for item in obj:
            nested = _walk_pdf_object(item, visited)
            if nested is not None:
                return nested
    return None


def _estimate_minimum_resolution(path: Path) -> float:
    try:
        document = fitz.open(str(path))
    except RuntimeError as exc:
        raise DocumentSafetyError("MALFORMED_PDF", f"Malformed PDF rejected: {exc}") from exc

    minimum_resolution = float("inf")
    for page in document:
        if page.get_text("words"):
            page_resolution = DEFAULT_TEXT_PAGE_DPI
        else:
            page_resolution = _estimate_page_image_resolution(document, page.number)
        minimum_resolution = min(minimum_resolution, page_resolution)

    if minimum_resolution == float("inf"):
        return DEFAULT_TEXT_PAGE_DPI
    return round(minimum_resolution, 2)


def _estimate_page_image_resolution(document: fitz.Document, page_index: int) -> float:
    page = document[page_index]
    images = page.get_images(full=True)
    if not images:
        return 0.0

    best_resolution = 0.0
    for image in images:
        xref = image[0]
        image_meta = document.extract_image(xref)
        if not image_meta:
            continue
        width_px = float(image_meta.get("width", 0))
        height_px = float(image_meta.get("height", 0))
        if width_px <= 0 or height_px <= 0:
            continue

        for rect in page.get_image_rects(xref):
            width_in = rect.width / 72.0
            height_in = rect.height / 72.0
            if width_in <= 0 or height_in <= 0:
                continue
            dpi_x = width_px / width_in
            dpi_y = height_px / height_in
            best_resolution = max(best_resolution, min(dpi_x, dpi_y))
    return round(best_resolution, 2)
