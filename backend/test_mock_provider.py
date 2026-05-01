import asyncio
from app.verifier_providers.mock_provider import MockRegistryProvider


async def main():
    provider = MockRegistryProvider()

    request = provider.prepare_request(
        session_id="s1",
        task_id="t1",
        verifier_key="local_mock_registry",
        input_payload={"name": "Kanak", "degree": "BTech"},
        redacted_payload={},
        timeout_ms=1000,
    )

    result = await provider.execute(request)

    print("Final Result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
    