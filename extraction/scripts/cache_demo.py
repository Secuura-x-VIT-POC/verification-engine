import os

from extraction.parser.document_parser import extract_document_data

# Define paths relative to the script location.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")
CACHE_DIR = os.path.join(BASE_DIR, "cached_results")


def generate_cached_results() -> None:
    """
    Process all PDFs in the samples directory and save the canonical JSON output.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(SAMPLES_DIR, exist_ok=True)

    pdf_files = [f for f in os.listdir(SAMPLES_DIR) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"No PDF files found in {SAMPLES_DIR}. Please add sample documents.")
        return

    for filename in pdf_files:
        filepath = os.path.join(SAMPLES_DIR, filename)
        print(f"Processing '{filename}'...")

        result = extract_document_data(filepath)

        cache_path = os.path.join(CACHE_DIR, f"{filename}.json")
        with open(cache_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(result.model_dump_json(indent=2))

        if result.is_successful:
            print(f"  [ok] Cached JSON saved to {cache_path}")
            if result.used_ocr:
                print("  ! Note: Local OCR fallback was triggered for this file.")
        else:
            print(f"  [error] Failed: {result.error_message}")


if __name__ == "__main__":
    print("Starting pre-processing for Demo Day...")
    generate_cached_results()
    print("Done.")
