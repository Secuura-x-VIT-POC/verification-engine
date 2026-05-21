import json
from mock_verifier_engine import MockVerifierEngine

def load_document(path):
    with open(path, "r") as f:
        return json.load(f)

def main():
    engine = MockVerifierEngine("test-documents/mock_db.json")
    doc = load_document("test-documents/doc1.json")
    result = engine.verify(doc)
    print("\n=== RESULT ===")
    print(result)

if __name__ == "__main__":
    main()