from __future__ import annotations

from .base import VerifierProvider
from .contracts import ProviderCapability, ProviderCapabilityCollection
from .http_client import SafeHttpJsonClient
from .policies import build_local_mock_config, load_provider_runtime_policy
from .providers import AcademicRegistryHttpProvider, IdentityHttpProvider, LocalMockProvider


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, VerifierProvider] = {}

    def register(self, provider: VerifierProvider) -> None:
        self._providers[provider.provider_key] = provider

    def get(self, provider_key: str) -> VerifierProvider | None:
        return self._providers.get(provider_key)

    def all_capabilities(self) -> list[ProviderCapability]:
        return [provider.get_capabilities() for provider in self._providers.values()]

    def find_provider(
        self,
        *,
        verifier_key: str,
        category: str,
        preferred_provider_key: str | None = None,
    ) -> VerifierProvider | None:
        if preferred_provider_key:
            preferred = self.get(preferred_provider_key)
            if preferred is not None and preferred.supports(verifier_key, category):
                return preferred
        for provider in self._providers.values():
            if provider.supports(verifier_key, category):
                return provider
        return None

    def capability_collection(self, session_id: str) -> ProviderCapabilityCollection:
        return ProviderCapabilityCollection(
            session_id=session_id,
            capabilities=self.all_capabilities(),
        )


def build_default_provider_registry() -> ProviderRegistry:
    policy = load_provider_runtime_policy()
    client = SafeHttpJsonClient(
        request_size_limit_bytes=policy.request_size_limit_bytes,
        response_size_limit_bytes=policy.response_size_limit_bytes,
    )
    registry = ProviderRegistry()

    identity_config = policy.config_for("identity_http")
    if identity_config is not None and policy.is_provider_enabled("identity_http"):
        registry.register(IdentityHttpProvider(config=identity_config, client=client))

    academic_config = policy.config_for("academic_registry_http")
    if academic_config is not None and policy.is_provider_enabled("academic_registry_http"):
        registry.register(AcademicRegistryHttpProvider(config=academic_config, client=client))

    registry.register(LocalMockProvider(build_local_mock_config()))
    return registry
