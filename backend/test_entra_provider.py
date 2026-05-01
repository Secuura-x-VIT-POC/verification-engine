import asyncio
from app.verifier_providers.entra_provider import EntraVerifiedIDProvider


async def main():
    provider = EntraVerifiedIDProvider()

    request = provider.prepare_request(
        session_id="s1",
        task_id="t1",
        verifier_key="entra_verified_id",
        input_payload={"name": "Kanak"},
        redacted_payload={},
        timeout_ms=1000,
    )

    result = await provider.execute(request)

    print("Entra Result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())