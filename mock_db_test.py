import os
import sys
import json
from pathlib import Path

# Add the project root to sys.path so we can import 'app'
# Assuming the script is in the root directory
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root / "backend"))

# Mock Environment Variables
os.environ["ENABLE_LOCAL_MOCK_VERIFIERS"] = "true"
os.environ["VERIFIER_LOCAL_VERIFICATION_STORE_PATH"] = "backend/app/verifier_providers/fixtures/local_verification_records.json"
os.environ["PYTHONPATH"] = str(project_root / "backend")

# Try to import core logic
try:
    from app.verifier_execution.service import build_execution_artifacts
    from app.trust.findings import build_trust_findings
    print("✅ Successfully imported Verification Engine modules.")
except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("\nTip: Make sure you are running this from the root folder and 'backend' folder exists.")
    sys.exit(1)

def run_test_scenario(name, student_name, reg_number, doc_type):
    print(f"\n--- Testing Scenario: {name} ---")
    
    # 1. Simulate the data as if it was just extracted from a PDF
    mock_extraction = {
        "field_candidates": [
            {
                "candidate_id": "name_001",
                "label": "Name",
                "raw_value": student_name,
                "category": "identity",
                "confidence": 0.95
            },
            {
                "candidate_id": "id_001",
                "label": "Registration Number" if doc_type == "academic_degree" else "Passport Number",
                "raw_value": reg_number,
                "category": "identity",
                "confidence": 0.98
            },
            {
                "candidate_id": "inst_001",
                "label": "University" if doc_type == "academic_degree" else "Issuer",
                "raw_value": "Vellore Institute of Technology" if doc_type == "academic_degree" else "Govt of India",
                "category": "academic" if doc_type == "academic_degree" else "identity",
                "confidence": 0.95
            }
        ],
        "document_type": doc_type
    }

    # 2. Trigger the Executor (The logic that talks to your JSON DB)
    try:
        artifacts = build_execution_artifacts(
            session_id="test-session-123",
            extraction_payload=mock_extraction
        )

        # 3. Inspect Credential Bundles (This is where the Decision Logic lives)
        bundles = artifacts["credential_bundles"].bundles
        
        match_found = False
        for bundle in bundles:
            status = bundle.final_outcome_color  # This will be GREEN, AMBER, or RED
            print(f"[{status}] {bundle.label}: {bundle.explanation}")
            
            if status == "GREEN":
                match_found = True
        
        if match_found:
            print(f"🏆 RESULT: SUCCESS! {name} was verified against Mock DB.")
        else:
            print(f"⚠️ RESULT: UNVERIFIED. No exact match in JSON for {name}.")

    except Exception as e:
        print(f"💥 Execution Error: {e}")

if __name__ == "__main__":
    # Test Case 1: Matching the VIT Record we created
    run_test_scenario("VIT Student (Match)", "ETHAN HUNT", "22BCE0001", "academic_degree")

    # Test Case 2: Matching the Passport Record
    run_test_scenario("Passport Holder (Match)", "VIOLET SHARMA", "L1234567", "passport")

    # Test Case 3: Mismatch Test (Correct name, wrong ID)
    run_test_scenario("Mismatch Test (Fail)", "ETHAN HUNT", "WRONG_ID_999", "academic_degree")
