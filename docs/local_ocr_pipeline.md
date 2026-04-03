# Local OCR Pipeline

## Purpose

The OCR path is local and privacy-preserving by default.

Precedence is:

1. native PDF text extraction
2. PaddleOCR for scanned or image-heavy pages
3. Tesseract as the bounded local fallback

Page images are not sent to NVIDIA or any third-party OCR service.

## Backend Modes

`OCR_BACKEND_MODE` supports:

- `AUTO`
- `NATIVE_ONLY`
- `PADDLE_PREFERRED`
- `TESSERACT_ONLY`

Default: `AUTO`

`AUTO` and `PADDLE_PREFERRED` both prefer PaddleOCR when it is available locally, then fall back to Tesseract.

## Optional Local Setup

Required baseline extraction dependencies remain unchanged.

PaddleOCR is optional. If it is not installed or cannot initialize locally, the pipeline falls back safely.

Typical local CPU setup:

```powershell
pip install paddlepaddle paddleocr
```

If your platform needs a different PaddlePaddle build, install the platform-appropriate package first and then install `paddleocr`.

## Docker Compose Setup

The default Docker Compose path already includes the local OCR runtime inside the backend image.

- host-side PaddleOCR installation is not required
- host-side Tesseract installation is not required
- the backend container includes both PaddleOCR support and Tesseract fallback
- Compose defaults to `OCR_BACKEND_MODE=AUTO`

For containerized demos, `docker compose up --build` is the intended operator workflow.

The Docker Compose stack also mounts the repo-local verification store file into the backend container:

- host path: `backend/app/verifier_providers/fixtures/local_verification_records.json`
- container path: `/app/backend/app/verifier_providers/fixtures/local_verification_records.json`

That keeps demo truth data editable without rebuilding the image.

## Useful Environment Variables

- `OCR_BACKEND_MODE`
- `OCR_DPI`
- `OCR_PREPROCESSING_ENABLED`
- `PADDLEOCR_ENABLED`
- `PADDLEOCR_LANGUAGE`
- `TESSERACT_ENABLED`
- `TESSERACT_CONFIG`

Container-friendly defaults are provided through `docker-compose.yml` and `.env.example`.

## Preprocessing

The local preprocessing chain is intentionally small and explainable:

- grayscale conversion
- autocontrast
- median denoising
- sharpening
- bounded upscaling for very small scans
- threshold binarization for low-contrast pages

## Metadata Surface

Extraction payloads may include `ocr_metadata` for debugging:

- backend mode
- OCR engine used
- engines used across pages
- whether native text was used
- whether OCR was applied
- fallback-used flag
- average OCR confidence
- preprocessing steps applied
- OCR pages
- page-level warning codes

This metadata is bounded and does not persist large raw OCR dumps.

## How To Confirm PaddleOCR Was Used

After processing a session, inspect the serialized session payload:

```powershell
curl http://localhost:8000/sessions/<session_id>
```

Relevant fields:

- `extraction.ocr_metadata.engine_used`
- `extraction.ocr_metadata.engines_used`
- `extraction.ocr_metadata.fallback_used`

Interpretation:

- `native_text`: OCR was not needed
- `paddleocr`: PaddleOCR handled the page OCR path
- `tesseract`: PaddleOCR was unavailable or failed and Tesseract was used as the bounded local fallback
