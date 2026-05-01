from app.verifier_execution.registry import build_default_verifier_registry


def main():
    registry = build_default_verifier_registry()

    candidates = registry.get_provider_candidates(
        claim_type="academic_degree",
        assurance_required="HIGH"
    )

    print("=== Provider Candidates ===")
    for c in candidates:
        print(c)


if __name__ == "__main__":
    main()