from __future__ import annotations

import hashlib
import re

from .models import ExtractionSignals, FieldCandidate, Sensitivity


def extract_from_tables(
    tables: dict[int, list[list[list[str]]]],
    *,
    extraction_method: str = "native",
) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    for page, page_tables in tables.items():
        for table_index, table in enumerate(page_tables):
            if not table:
                continue
            if _looks_like_key_value_table(table):
                candidates.extend(_extract_key_value_table(table, page, table_index, extraction_method))
                continue
            candidates.extend(_extract_header_table(table, page, table_index, extraction_method))
    return candidates


def _looks_like_key_value_table(table: list[list[str]]) -> bool:
    if not table:
        return False
    return all(len(row) == 2 for row in table if row)


def _extract_key_value_table(table: list[list[str]], page: int, table_index: int, extraction_method: str) -> list[FieldCandidate]:
    output: list[FieldCandidate] = []
    for row_index, row in enumerate(table):
        if len(row) < 2:
            continue
        label = str(row[0] or "").strip()
        value = str(row[1] or "").strip()
        if not label or not value:
            continue
        output.append(
            _candidate(
                label=label,
                value=value,
                category=_infer_category(label, value),
                page=page,
                extraction_method=extraction_method,
                salt=f"{table_index}-{row_index}",
            )
        )
    return output


def _extract_header_table(table: list[list[str]], page: int, table_index: int, extraction_method: str) -> list[FieldCandidate]:
    output: list[FieldCandidate] = []
    if len(table) < 2:
        return output
    headers = [str(cell or "").strip() for cell in table[0]]
    for row_index, row in enumerate(table[1:], start=1):
        if len(row) != len(headers):
            continue
        row_label = str(row[0] or "").strip()
        for col_index, header in enumerate(headers[1:], start=1):
            value = str(row[col_index] or "").strip()
            if not header or not value:
                continue
            candidate_label = f"{row_label} {header}".strip() if row_label else header
            output.append(
                _candidate(
                    label=candidate_label,
                    value=value,
                    category=_infer_category(header, value),
                    page=page,
                    extraction_method=extraction_method,
                    salt=f"{table_index}-{row_index}-{col_index}",
                )
            )
    return output


def _candidate(*, label: str, value: str, category: str, page: int, extraction_method: str, salt: str) -> FieldCandidate:
    field_id = f"tbl_{hashlib.sha1(f'{page}|{label}|{value}|{salt}'.encode('utf-8')).hexdigest()[:12]}"
    return FieldCandidate(
        field_id=field_id,
        label=label.strip(),
        raw_value=value.strip(),
        normalized_value=_normalize_value(value),
        category=category,  # type: ignore[arg-type]
        page=page,
        confidence=0.68,
        signals=ExtractionSignals(
            regex_score=0.0,
            layout_score=0.65,
            llm_score=0.0,
            ner_score=0.0,
            ocr_confidence=0.9 if extraction_method == "native" else 0.7,
            semantic_score=0.72,
            frequency=1,
        ),
        is_pii=category in {"personal_name", "address", "contact", "identifier"},
        sensitivity=Sensitivity.HIGH if category in {"personal_name", "identifier"} else Sensitivity.MEDIUM if category in {"address", "contact"} else Sensitivity.LOW,
        requires_verification=category != "other",
        source_text=label.strip(),
        extraction_method=extraction_method,  # type: ignore[arg-type]
        detected_by=["table"],
    )


def _infer_category(label: str, value: str) -> str:
    haystack = f"{label} {value}".lower()
    digits = re.sub(r"\D", "", value)
    if any(token in haystack for token in ("name",)):
        return "personal_name"
    if any(token in haystack for token in ("institution", "university", "college", "school", "board")):
        return "institution"
    if any(token in haystack for token in ("cgpa", "gpa", "marks", "grade", "score", "result", "percentage")):
        return "score"
    if any(token in haystack for token in ("date", "dob", "birth", "issue", "expiry")):
        return "date"
    if any(token in haystack for token in ("address", "street", "city", "state", "zip", "pin")):
        return "address"
    if any(token in haystack for token in ("email", "phone", "mobile", "contact")):
        return "contact"
    if any(token in haystack for token in ("id", "number", "roll", "registration", "seat")) or len(digits) in {10, 12}:
        return "identifier"
    return "other"


def _normalize_value(value: str) -> str:
    return " ".join(str(value or "").split())
