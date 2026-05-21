import os
import sys
import json
from pathlib import Path

# Setup paths
backend_path = Path("/mnt/d/VIT/Semester - 4/EDI/project4/backend")
sys.path.append(str(backend_path))

from app.verifier_providers.providers.local_mock import LocalMockProvider
from app.verifier_providers.contracts import ProviderRequest
from app.verifier_providers.policies import ProviderConfig

def test_provider(fixture_path_rel, doc_path_rel):
    print(f"\n--- Testing with Fixture: {fixture_path_rel} and Doc: {doc_path_rel} ---")
    
    config = ProviderConfig(
        provider_key="local_mock",
        provider_label="Local Mock Provider",
        enabled=True,
        base_url=None,
        timeout_ms=50,
        retry_budget=0,
        outbound_mode="LOCAL_ONLY",
        allow_document_upload=False,
        field_lookup_preferred=True,
        require_minimization=True,
        operating_mode="LOCAL_MOCK",
        execution_environment_label="Test Env"
    )
    
    provider = LocalMockProvider(config)
    
    # Load doc
    with open(backend_path / doc_path_rel, "r") as f:
        doc = json.load(f)
    
    # Set environment variable for the provider to find the fixture
    os.environ["VERIFIER_LOCAL_VERIFICATION_STORE_PATH"] = str(backend_path / fixture_path_rel)
    
    # Mock a request for one of the fields, e.g., 'name'
    request = ProviderRequest(
        request_id="test-req",
        session_id="test-session",
        task_id="test-task",
        verifier_key="academic_registry",
        provider_key="local_mock",
        input_payload={
            "category": doc["category"],
            "label": "Name",
            "value": doc["fields"]["name"],
            "document_type": "academic_degree"
        },
        redacted_payload={},
        timeout_ms=50,
        metadata={"category": doc["category"]}
    )
    
    response = provider.execute(request)
    print(f"Status: {response.response_summary.get('match_status')}")
    print(f"Matched Fields: {response.matched_fields}")
    print(f"Mismatched Fields: {response.mismatched_fields}")
    print(f"Missing Fields: {response.missing_fields}")
    print(f"Reason Codes: {response.reason_codes}")

if __name__ == "__main__":
    # Test doc1 with both fixtures
    test_provider("app/verifier_providers/fixtures/local_verification_records.json", "test-documents/doc1.json")
    test_provider("app/verifier_providers/mock_data/registry.json", "test-documents/doc1.json")
    
    # Test doc3 (which should be mismatch)
    test_provider("app/verifier_providers/mock_data/registry.json", "test-documents/doc3.json")
