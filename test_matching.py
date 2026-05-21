import os
import sys
import json
from pathlib import Path

# Setup paths
backend_path = Path("/mnt/d/VIT/Semester - 4/EDI/project4/backend")
sys.path.append(str(backend_path))

from app.verifier_providers.providers.local_mock import LocalMockProvider, _record_supports_route
from app.verifier_providers.contracts import ProviderRequest
from app.verifier_providers.policies import ProviderConfig

def test_matching():
    record = {
        "record_id": "acad_1",
        "verifier_keys": ["academic_registry"],
        "categories": ["academic"]
    }
    
    # This is what graph.py might send
    verifier_key = "academic_registry"
    category = "academic_degree" # or "credential"
    
    supports = _record_supports_route(record, verifier_key=verifier_key, category=category, document_type="")
    print(f"Record supports route (category='{category}'): {supports}")

    category2 = "academic"
    supports2 = _record_supports_route(record, verifier_key=verifier_key, category=category2, document_type="")
    print(f"Record supports route (category='{category2}'): {supports2}")

if __name__ == "__main__":
    test_matching()
