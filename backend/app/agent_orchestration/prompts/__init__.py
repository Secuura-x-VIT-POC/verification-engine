from __future__ import annotations

from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def load_prompt_bundle() -> dict[str, str]:
    return {
        "document_understanding": load_prompt("document_understanding"),
        "credential_grouping": load_prompt("credential_grouping"),
        "route_recommendation": load_prompt("route_recommendation"),
        "explanation_synthesis": load_prompt("explanation_synthesis"),
    }
