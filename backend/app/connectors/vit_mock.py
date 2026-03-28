import json
from app.connectors.schema import ConnectorResponse

def verify(data: dict):
    with open("fixtures/vit_registry.json") as f:
        db = json.load(f)

    matched = {}
    mismatched = []

    for key in data:
        if key in db and data[key] == db[key]:
            matched[key] = data[key]
        else:
            mismatched.append(key)

    status = "VERIFIED" if not mismatched else "NOT_VERIFIED"

    return ConnectorResponse(
        connector_id="vit",
        status=status,
        reason_codes=mismatched,
        matched_claims=matched,
        mismatched_claims={key: data.get(key) for key in mismatched}
    )