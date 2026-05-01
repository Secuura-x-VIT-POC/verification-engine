from app.verifier_execution.registry import build_default_provider_registry


def main():
    registry = build_default_provider_registry()

    print("=== Providers in Registry ===")
    for cap in registry.all_capabilities():
        print(f"{cap.provider_key} | {cap.provider_label}")


if __name__ == "__main__":
    main()
    