from __future__ import annotations

import os
import re
from typing import Any


def llm_classification_enabled() -> bool:
    raw = os.getenv("ENABLE_LLM_CLASSIFICATION")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def classify_candidate(
    *,
    label: str,
    value: str,
    context: str = "",
    llm_client: Any = None,
) -> dict[str, Any]:
    if llm_client is not None:
        try:
            if callable(llm_client):
                result = llm_client(label=label, value=value, context=context)
            elif hasattr(llm_client, "classify"):
                result = llm_client.classify(label=label, value=value, context=context)
            elif hasattr(llm_client, "invoke"):
                result = llm_client.invoke({"label": label, "value": value, "context": context})
            else:
                result = None
            if isinstance(result, dict):
                return _normalize_result(result, fallback_label=label, fallback_value=value, source="llm")
        except Exception:
            pass

    return _heuristic_classification(label=label, value=value, context=context)


def _heuristic_classification(*, label: str, value: str, context: str) -> dict[str, Any]:
    label_text = f"{label} {context}".lower()
    compact = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    digits = re.sub(r"\D", "", value or "")
    normalized_label = " ".join(str(label or "").lower().split())

    if any(
        token in normalized_label
        for token in (
            "languages",
            "web technologies",
            "libraries & frameworks",
            "libraries and frameworks",
            "technology/languages used",
            "technical competencies",
            "core cs concepts",
            "skills",
        )
    ):
        return {"label": label, "category": "other", "score": 0.35, "source": "heuristic"}

    if any(token in label_text for token in ("institution", "university", "college", "school", "board", "issuer")):
        return {"label": label, "category": "institution", "score": 0.78, "source": "heuristic"}
    if any(token in label_text for token in ("degree", "credential", "certificate", "program", "course")):
        return {"label": label, "category": "credential_title", "score": 0.74, "source": "heuristic"}
    if any(token in label_text for token in ("cgpa", "gpa", "marks", "grade", "score", "result", "percentage")):
        return {"label": label, "category": "score", "score": 0.79, "source": "heuristic"}
    if any(token in label_text for token in ("date", "dob", "birth", "issued", "expiry", "valid")):
        return {"label": label, "category": "date", "score": 0.77, "source": "heuristic"}
    if any(token in label_text for token in ("address", "street", "city", "state", "pin", "zip")):
        return {"label": label, "category": "address", "score": 0.74, "source": "heuristic"}
    if any(token in label_text for token in ("email", "phone", "mobile", "contact")):
        return {"label": label, "category": "contact", "score": 0.75, "source": "heuristic"}
    if any(token in label_text for token in ("signature",)) or value.strip().lower() == "signature":
        return {"label": label, "category": "signature", "score": 0.8, "source": "heuristic"}
    if any(token in label_text for token in ("seal", "stamp")):
        return {"label": label, "category": "seal", "score": 0.8, "source": "heuristic"}
    if any(token in label_text for token in ("student name", "holder name", "full name", "applicant name", "name")):
        return {"label": label, "category": "personal_name", "score": 0.76, "source": "heuristic"}
    if len(digits) in {10, 12} or (re.fullmatch(r"[A-Z0-9-]{5,24}", compact) and re.search(r"\d", compact)):
        return {"label": label, "category": "identifier", "score": 0.73, "source": "heuristic"}
    return {"label": label, "category": "other", "score": 0.58, "source": "heuristic"}


def _normalize_result(result: dict[str, Any], *, fallback_label: str, fallback_value: str, source: str) -> dict[str, Any]:
    category = str(result.get("category") or "other").strip().lower()
    if category not in {
        "identifier",
        "personal_name",
        "date",
        "institution",
        "credential_title",
        "score",
        "address",
        "contact",
        "signature",
        "seal",
        "other",
    }:
        category = _heuristic_classification(label=fallback_label, value=fallback_value, context="").get("category", "other")
    return {
        "label": str(result.get("label") or fallback_label),
        "category": category,
        "score": max(0.0, min(1.0, float(result.get("score") or result.get("confidence") or 0.0))),
        "source": source,
    }
