import os
import sys
import unittest
from unittest.mock import patch


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.security.pdf_validator import (  # noqa: E402
    PDF_ACTIVE_CONTENT_STRIPPED_NOTICE,
    PDFValidationError,
    make_image_only_pdf,
    validate_pdf,
    validate_pdf_report,
    validate_pdf_upload_metadata,
)
from backend.app.sessions.routes import UploadResponse, normalize_notices  # noqa: E402


class _FakePdfReader:
    def __init__(self, *_args, encrypted=False, pages=1, metadata=None, trailer=None):
        self.pages = [object()] * pages
        self.is_encrypted = encrypted
        self.metadata = metadata or {}
        self.trailer = trailer or {}


class PdfSecurityTests(unittest.TestCase):
    def test_upload_metadata_accepts_pdf_extension_and_pdf_mime(self):
        validate_pdf_upload_metadata("document.pdf", "application/pdf")
        validate_pdf_upload_metadata("document.pdf", None)

    def test_upload_metadata_rejects_non_pdf_extension(self):
        with self.assertRaisesRegex(PDFValidationError, "Only PDF files"):
            validate_pdf_upload_metadata("document.txt", "application/pdf")

    def test_upload_metadata_rejects_clear_non_pdf_mime(self):
        with self.assertRaisesRegex(PDFValidationError, "Only PDF content types"):
            validate_pdf_upload_metadata("document.pdf", "text/plain")

    def test_magic_bytes_are_required_before_parser_runs(self):
        with self.assertRaisesRegex(PDFValidationError, "signature"):
            validate_pdf(b"not a pdf")

    def test_dangerous_action_markers_are_rejected(self):
        for marker in (b"/JavaScript", b"/JS", b"/OpenAction", b"/AA", b"/Launch", b"/EmbeddedFiles"):
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(PDFValidationError, "active or embedded"):
                    validate_pdf(b"%PDF-1.7\n" + marker + b"\n%%EOF")

    def test_encrypted_pdf_is_rejected(self):
        with patch("backend.app.security.pdf_validator.PdfReader", return_value=_FakePdfReader(encrypted=True)):
            with self.assertRaisesRegex(PDFValidationError, "Encrypted"):
                validate_pdf(b"%PDF-1.7\n%%EOF")

    def test_malformed_pdf_is_rejected(self):
        with patch("backend.app.security.pdf_validator.PdfReader", side_effect=RuntimeError("bad pdf")):
            with self.assertRaisesRegex(PDFValidationError, "Malformed"):
                validate_pdf(b"%PDF-1.7\n%%EOF")

    def test_valid_pdf_returns_without_error(self):
        with patch("backend.app.security.pdf_validator.PdfReader", return_value=_FakePdfReader()):
            validate_pdf(b"%PDF-1.7\n%%EOF")

    def test_upload_response_schema_allows_sanitized_notices(self):
        response = UploadResponse(
            message="File uploaded securely",
            filename="safe.pdf",
            session_id="session-1",
            status="UPLOADED_PENDING_REVIEW",
            notices=normalize_notices([PDF_ACTIVE_CONTENT_STRIPPED_NOTICE, {"message": "raw path C:\\secret"}]),
        )

        payload = response.model_dump(mode="json")

        self.assertEqual(payload["notices"], [PDF_ACTIVE_CONTENT_STRIPPED_NOTICE])

    def test_active_content_pdf_can_be_flattened_to_safe_image_only_pdf(self):
        try:
            import fitz
        except Exception:
            self.skipTest("PyMuPDF is not available")

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Safe flatten regression")
        pdf_bytes = document.tobytes()
        document.close()
        active_pdf = pdf_bytes + b"\n/JavaScript\n"

        report = validate_pdf_report(active_pdf, allow_active_content=True)
        result = make_image_only_pdf(active_pdf)

        self.assertTrue(report.has_active_or_embedded_content)
        self.assertEqual(result.notice_code, PDF_ACTIVE_CONTENT_STRIPPED_NOTICE)
        self.assertFalse(result.safe_report.has_active_or_embedded_content)
        validate_pdf(result.safe_pdf_bytes)


if __name__ == "__main__":
    unittest.main()
