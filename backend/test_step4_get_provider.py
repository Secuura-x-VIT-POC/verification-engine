from app.verifier_execution.registry import build_default_provider_registry


def main():
    registry = build_default_provider_registry()

    provider = registry.get("local_mock")

    print("Provider:")
    print(provider)

    print("\nCapabilities:")
    print(provider.get_capabilities())


if __name__ == "__main__":
    main()