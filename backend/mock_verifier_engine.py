import json
from pathlib import Path

class MockVerifierEngine:
    def __init__(self, db_path):
        base_dir = Path(__file__).resolve().parent
        full_path = base_dir / db_path

        with open(full_path, "r") as f:
            self.db = json.load(f)

    def verify(self, document):
        category = document["category"]
        fields = document["fields"]

        if category == "academic":
            records = self.db.get("academic_registry", [])
        elif category == "identity":
            records = self.db.get("identity_db", [])
        else:
            return {"status": "AMBER", "reason": "UNKNOWN_CATEGORY"}

        matched_fields = {}
        mismatched_fields = {}
        missing_fields = []

        # assume first record (since mock DB is small)
        record = records[0] if records else {}

        for key in record.keys():
            if key in fields:
                if record[key] == fields[key]:
                    matched_fields[key] = True
                else:
                    mismatched_fields[key] = True
            else:
                missing_fields.append(key)

        # DECISION LOGIC (IMPORTANT)
        if mismatched_fields:
            status = "RED"
        elif missing_fields:
            status = "AMBER"
        else:
            status = "GREEN"

        return {
            "status": status,
            "matched_fields": matched_fields,
            "mismatched_fields": mismatched_fields,
            "missing_fields": missing_fields,
        }