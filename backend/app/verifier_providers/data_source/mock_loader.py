import json
from pathlib import Path


class MockDataSource:
    def __init__(self, file_name: str):
        base_path = Path(__file__).resolve().parents[2] / "mock_data"
        self.path = base_path / file_name

    def load(self):
        with open(self.path, "r") as f:
            return json.load(f)

    def find_match(self, query: dict):
        data = self.load()

        for record in data.get("records", []):
            if all(record.get(k) == v for k, v in query.items()):
                return record

        return None