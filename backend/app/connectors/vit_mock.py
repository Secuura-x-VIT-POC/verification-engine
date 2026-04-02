from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import ConnectorResponse


BASE_DIR = Path(__file__).resolve().parent


def verify(data: dict) -> ConnectorResponse:
    file_path = BASE_DIR / "fixtures" / "vit_registry.json"
    with file_path.open(encoding="utf-8") as fixture_file:
        registry_data = json.load(fixture_file)

    matched: dict[str, object] = {}
    mismatched: dict[str, object] = {}

    for key, value in data.items():
        if key in registry_data and registry_data[key] == value:
            matched[key] = value
        else:
            mismatched[key] = value

    status = "VERIFIED" if not mismatched else "NOT_VERIFIED"
    reason_codes = ["REGISTRY_MATCH"] if status == "VERIFIED" else [
        f"MISMATCH_{key.upper()}" for key in mismatched
    ]

    return ConnectorResponse(
        connector_id="vit_registry",
        assurance_class="HIGH",
        status=status,
        reason_codes=reason_codes,
        matched_claims=matched,
        mismatched_claims=mismatched,
        source_timestamp=datetime.now(timezone.utc),
        technical_state="SUCCESS",
    )
