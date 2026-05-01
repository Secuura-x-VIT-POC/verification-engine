import asyncio
from app.verifier_providers.base import VerifierProvider


# Dummy provider just to test interface
class DummyProvider(VerifierProvider):
    provider_id = "dummy"
    provider_label = "Dummy Provider"
    provider_mode = "mock"

    def get_capabilities(self):
        return type("Cap", (), {
            "supported_verifier_keys": ["dummy"],
            "supported_categories": ["test"],
            "enabled": True
        })()

    def prepare_request(self, **kwargs):
        return {"prepared": True}

    async def execute(self, request):
        return {"status": "MATCHED"}

    def normalize_response(self, **kwargs):
        return {"normalized": True}


async def main():
    provider = DummyProvider()

    print("Provider ID:", provider.provider_id)
    print("Mode:", provider.provider_mode)

    print("Supports:", provider.supports("dummy", "test"))

    req = provider.prepare_request(
        session_id="s1",
        task_id="t1",
        verifier_key="dummy",
        input_payload={"name": "test"},
        redacted_payload={},
        timeout_ms=1000
    )
    print("Prepared:", req)

    result = await provider.execute(req)
    print("Execute Result:", result)

    norm = provider.normalize_response(
        request=req,
        payload=result,
        technical_status="SUCCESS",
        http_status=200,
        latency_ms=50
    )
    print("Normalized:", norm)


if __name__ == "__main__":
    asyncio.run(main())