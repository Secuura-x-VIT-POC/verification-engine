import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile

from extraction.parser.document_parser import extract_document_data
from extraction.schema.models import ExtractionResult

CACHED_RESULTS_DIR = Path(__file__).resolve().parent / "cached_results"

app = FastAPI(
    title="Verification Extraction Service",
    version="1.0.0",
    description="Document extraction service for the verification engine.",
)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractionResult)
async def extract_uploaded_file(file: UploadFile = File(...)) -> ExtractionResult:
    return await _extract_from_upload(file)


async def _extract_from_upload(file: UploadFile) -> ExtractionResult:
    suffix = Path(file.filename or "upload.bin").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        shutil.copyfileobj(file.file, temp_file)

    try:
        result = extract_document_data(str(temp_path))
        if not result.is_successful:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason_code": result.reason_code,
                    "message": result.error_message or "Extraction failed.",
                },
            )

        if result.metadata is not None and file.filename:
            result.metadata.file_name = file.filename
        _cache_result(result, file.filename)
        return result
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/extract/batch", response_model=List[ExtractionResult])
async def extract_uploaded_files(files: List[UploadFile] = File(...)) -> List[ExtractionResult]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    return [await _extract_from_upload(file) for file in files]


def _cache_result(result: ExtractionResult, original_file_name: str | None) -> None:
    CACHED_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_name = original_file_name or (result.metadata.file_name if result.metadata else "extraction_result.pdf")
    cache_name = f"{Path(file_name).name}.json"
    cache_path = CACHED_RESULTS_DIR / cache_name
    cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
