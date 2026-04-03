import argparse
import json
from pathlib import Path

from extraction.parser.document_parser import extract_document_data

CACHED_RESULTS_DIR = Path(__file__).resolve().parents[1] / "cached_results"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run extraction on one file or every file in a directory.")
    parser.add_argument("path", help="Path to a document or a directory of documents.")
    parser.add_argument(
        "--output-dir",
        help="Optional directory where JSON outputs should be saved. Defaults to extraction/cached_results.",
    )
    args = parser.parse_args()

    target_path = Path(args.path)
    output_dir = Path(args.output_dir) if args.output_dir else CACHED_RESULTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    files = _collect_files(target_path)
    for file_path in files:
        result = extract_document_data(str(file_path))
        payload = json.dumps(result.model_dump(), indent=2, ensure_ascii=True)
        output_path = output_dir / f"{file_path.name}.json"
        output_path.write_text(payload, encoding="utf-8")
        print(f"\n=== {file_path.name} ===")
        print(f"saved: {output_path}")
        print(payload)


def _collect_files(target_path: Path) -> list[Path]:
    if target_path.is_file():
        return [target_path]
    if target_path.is_dir():
        supported_suffixes = {".pdf"}
        return sorted(
            file_path
            for file_path in target_path.iterdir()
            if file_path.is_file() and file_path.suffix.lower() in supported_suffixes
        )
    raise FileNotFoundError(f"Path not found: {target_path}")


if __name__ == "__main__":
    main()
