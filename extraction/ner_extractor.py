from __future__ import annotations

import re

from .models import EvidenceLine

SECTION_HEADER_PATTERN = re.compile(r"^[A-Z][A-Z\s&/-]{3,}$")
TECH_KEYWORDS = {
    "python",
    "java",
    "javascript",
    "django",
    "reactjs",
    "react",
    "numpy",
    "pandas",
    "matplotlib",
    "streamlit",
    "langchain",
    "docker",
    "opencv",
    "tensorflow",
    "keras",
    "html",
    "css",
    "dsa",
    "ai/ml",
    "ai",
    "ml",
    "rag",
    "deep learning",
    "data structures",
    "algorithms",
}


def extract_named_entities(lines: list[EvidenceLine]) -> list[dict]:
    entities = _extract_spacy_entities(lines)
    if entities:
        return entities
    return _extract_heuristic_entities(lines)


def _extract_spacy_entities(lines: list[EvidenceLine]) -> list[dict]:
    try:
        import spacy
    except Exception:
        return []

    model = None
    for name in ("en_core_web_sm",):
        try:
            model = spacy.load(name)  # type: ignore[arg-type]
            break
        except Exception:
            continue
    if model is None:
        return []

    results: list[dict] = []
    for line in lines:
        doc = model(line.text)
        for ent in doc.ents:
            label = ent.label_.upper()
            if label == "PERSON":
                category = "personal_name"
            elif label in {"ORG", "FAC"}:
                category = "institution"
            elif label == "DATE":
                category = "date"
            elif label in {"GPE", "LOC"}:
                category = "address"
            else:
                continue
            if not _entity_allowed_in_context(category, ent.text, line.text):
                continue
            results.append(
                {
                    "label": _friendly_entity_label(category),
                    "value": ent.text.strip(),
                    "category": category,
                    "page": line.page,
                    "score": 0.8,
                }
            )
    return results


def _extract_heuristic_entities(lines: list[EvidenceLine]) -> list[dict]:
    results: list[dict] = []
    name_pattern = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b")
    uppercase_name_pattern = re.compile(r"^[A-Z]{2,}(?:\s+[A-Z]{2,}){1,3}$")
    uppercase_name_prefix_pattern = re.compile(r"^([A-Z]{2,}(?:\s+[A-Z]{2,}){1,3})\b")
    org_keywords = ("University", "College", "Institute", "School", "Board", "Authority")
    date_pattern = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
    for line in lines:
        normalized_line = " ".join(line.text.split())
        if ":" not in line.text and uppercase_name_pattern.fullmatch(normalized_line) and _entity_allowed_in_context("personal_name", normalized_line, line.text):
            results.append(
                {
                    "label": "Detected Name",
                    "value": normalized_line,
                    "category": "personal_name",
                    "page": line.page,
                    "score": 0.74,
                }
            )
        if ":" not in line.text:
            prefix_match = uppercase_name_prefix_pattern.match(normalized_line)
            if prefix_match and _entity_allowed_in_context("personal_name", prefix_match.group(1), line.text):
                results.append(
                    {
                        "label": "Detected Name",
                        "value": prefix_match.group(1),
                        "category": "personal_name",
                        "page": line.page,
                        "score": 0.72,
                    }
                )
        if ":" not in line.text and not _looks_like_section_header(line.text):
            name_match = name_pattern.search(line.text)
            if name_match and not any(char.isdigit() for char in name_match.group(0)) and _entity_allowed_in_context("personal_name", name_match.group(0), line.text):
                results.append(
                    {
                        "label": "Detected Name",
                        "value": name_match.group(0),
                        "category": "personal_name",
                        "page": line.page,
                        "score": 0.68,
                    }
                )
        for keyword in org_keywords:
            if keyword.lower() in line.text.lower():
                value = line.text.split(":", 1)[1].strip() if ":" in line.text else line.text.strip()
                if not _entity_allowed_in_context("institution", value, line.text):
                    break
                results.append(
                    {
                        "label": "Detected Institution",
                        "value": value,
                        "category": "institution",
                        "page": line.page,
                        "score": 0.66,
                    }
                )
                break
        date_match = date_pattern.search(line.text)
        if date_match:
            results.append(
                {
                    "label": "Detected Date",
                    "value": date_match.group(0),
                    "category": "date",
                    "page": line.page,
                    "score": 0.62,
                }
            )
    return results


def _friendly_entity_label(category: str) -> str:
    return {
        "personal_name": "Detected Name",
        "institution": "Detected Institution",
        "date": "Detected Date",
        "address": "Detected Address",
    }.get(category, "Detected Field")


def _entity_allowed_in_context(category: str, value: str, line_text: str) -> bool:
    normalized_value = " ".join(str(value or "").strip().split())
    if not normalized_value:
        return False
    lowered_value = normalized_value.lower()
    lowered_line = str(line_text or "").lower()

    if _looks_like_section_header(normalized_value):
        if category == "personal_name" and re.fullmatch(r"[A-Z]{2,}(?:\s+[A-Z]{2,}){1,3}", normalized_value):
            return True
        return False
    if lowered_value in TECH_KEYWORDS:
        return False
    if any(token in lowered_value for token in ("technology/languages used", "technical competencies", "core cs concepts")):
        return False

    if category == "personal_name":
        if ":" in line_text and not any(token in lowered_line for token in ("name", "student", "holder", "applicant")):
            return False
        if any(token in lowered_value for token in ("assistant", "management system", "medical", "finance", "project")):
            return False
    elif category == "institution":
        if ":" in line_text and not any(token in lowered_line for token in ("institution", "university", "college", "school", "board", "issuer", "company", "organization")):
            return False
        if any(token in lowered_value for token in ("python", "django", "react", "docker", "tensorflow", "keras", "html", "css", "javascript")):
            return False
    elif category == "address":
        if not any(token in lowered_line for token in ("address", "street", "city", "state", "pin", "zip", "road", "lane")):
            return False
    return True


def _looks_like_section_header(value: str) -> bool:
    compact = " ".join(str(value or "").split())
    return bool(compact) and bool(SECTION_HEADER_PATTERN.fullmatch(compact))
