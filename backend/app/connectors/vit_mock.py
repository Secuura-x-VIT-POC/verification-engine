import json
from app.connectors.schema import ConnectorResponse
from app.sessions.constants import SessionState
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
def verify(data: dict):
    file_path = BASE_DIR / "fixtures" / "vit_registry.json"
    with open(file_path) as f:
        db = json.load(f)

    matched = {}
    mismatched = []

    for key in data:
        if key in db and data[key] == db[key]:
            matched[key] = data[key]
        else:
            mismatched.append(key)

    status = SessionState.VERIFIED if not mismatched else "NOT_VERIFIED"

    return ConnectorResponse(
        connector_id="vit",
        status=status,
        reason_codes=mismatched,
        matched_claims=matched,
        mismatched_claims={key: data.get(key) for key in mismatched}
    )