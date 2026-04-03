from __future__ import annotations

from .base import AgentProvider, AgentProviderUnavailable


class NvidiaProvider(AgentProvider):
    provider_key = "nvidia"
    external_provider = True

    def is_available(self) -> tuple[bool, str | None]:
        if not self.policy.external_provider_enabled:
            return False, "External agent providers are disabled by policy."
        if not self.policy.nvidia_base_url or not self.policy.nvidia_model or not self.policy.nvidia_api_key:
            return False, "NVIDIA provider configuration is incomplete."
        return False, "NVIDIA provider is intentionally stubbed in this stage and falls back to the deterministic provider."

    def analyze_document(self, **kwargs):
        raise AgentProviderUnavailable("NVIDIA provider is not active in this repository configuration.")

    def group_credentials(self, **kwargs):
        raise AgentProviderUnavailable("NVIDIA provider is not active in this repository configuration.")

    def recommend_routes(self, **kwargs):
        raise AgentProviderUnavailable("NVIDIA provider is not active in this repository configuration.")

    def generate_explanations(self, **kwargs):
        raise AgentProviderUnavailable("NVIDIA provider is not active in this repository configuration.")
