import sys
import os

# Add project root to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.trust.trust_engine import evaluate_trust

def run_tests():
    tests = [
        {
            "name": "GREEN - valid verified connector",
            "policy": {
                "requires_high_assurance": True,
                "required_connectors": ["vit_registry"]
            },
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True}
                ]
            },
            "connectors": [
                {
                    "connector_id": "vit_registry",
                    "status": "VERIFIED",
                    "assurance_class": "HIGH",
                    "mismatched_claims": []
                }
            ],
            "expected": "GREEN"
        },

        {
            "name": "RED - tampered document",
            "policy": {"requires_high_assurance": True, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": True,
                "critical_tamper_signal": True,
                "fields": []
            },
            "connectors": [],
            "expected": "RED"
        },

        {
            "name": "RED - missing grounding",
            "policy": {"requires_high_assurance": True, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "degree", "is_mandatory": True, "is_grounded": False}
                ]
            },
            "connectors": [],
            "expected": "RED"
        },

        {
            "name": "RED - connector mismatch",
            "policy": {"requires_high_assurance": True, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True}
                ]
            },
            "connectors": [
                {
                    "connector_id": "vit_registry",
                    "status": "VERIFIED",
                    "assurance_class": "HIGH",
                    "mismatched_claims": ["name"]
                }
            ],
            "expected": "RED"
        },

        {
            "name": "RED - required connector timeout",
            "policy": {"requires_high_assurance": True, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True}
                ]
            },
            "connectors": [
                {
                    "connector_id": "vit_registry",
                    "status": "TIMEOUT_AFTER_RETRIES",
                    "assurance_class": "HIGH",
                    "mismatched_claims": []
                }
            ],
            "expected": "RED"
        },

        {
            "name": "AMBER - optional connector timeout",
            "policy": {"requires_high_assurance": False, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True}
                ]
            },
            "connectors": [
                {
                    "connector_id": "vit_registry",
                    "status": "TIMEOUT_AFTER_RETRIES",
                    "assurance_class": "LOW",
                    "mismatched_claims": []
                }
            ],
            "expected": "AMBER"
        },

        {
            "name": "AMBER - no verified connector but optional",
            "policy": {"requires_high_assurance": False, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True}
                ]
            },
            "connectors": [
                {
                    "connector_id": "vit_registry",
                    "status": "NOT_FOUND",
                    "assurance_class": "LOW",
                    "mismatched_claims": []
                }
            ],
            "expected": "AMBER"
        },

        {
            "name": "RED - no connector response (required)",
            "policy": {"requires_high_assurance": True, "required_connectors": ["vit_registry"]},
            "extraction": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True}
                ]
            },
            "connectors": [],
            "expected": "RED"
        }
    ]

    passed = 0

    for test in tests:
        result = evaluate_trust(
            test["policy"],
            test["extraction"],
            test["connectors"]
        )

        outcome = result["outcome"]
        status = "PASS" if outcome == test["expected"] else "FAIL"

        print(f"{status} | {test['name']}")
        print(f"  Expected: {test['expected']}, Got: {outcome}")
        print(f"  Reason Codes: {result['reason_codes']}")
        print("-" * 50)

        if status == "PASS":
            passed += 1

    print(f"\n{passed}/{len(tests)} tests passed")


if __name__ == "__main__":
    run_tests()