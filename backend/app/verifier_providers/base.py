from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import ProviderCapability, ProviderRequest, ProviderResponse


class ProviderExecutionFailure(Exception):
    def __init__(self, message: str, *, technical_status: str = "FAILED", http_status: int | None = None):
        super().__init__(message)
        self.technical_status = technical_status
        self.http_status = http_status


class VerifierProvider(ABC):
    provider_key = ""
    provider_label = ""

    @abstractmethod
    def get_capabilities(self) -> ProviderCapability:
        ...

    @abstractmethod
    def prepare_request(
        self,
        *,
        session_id: str,
        task_id: str,
        verifier_key: str,
        input_payload: dict,
        redacted_payload: dict,
        timeout_ms: int,
        metadata: dict | None = None,
    ) -> ProviderRequest:
        ...

    @abstractmethod
    def execute(self, request: ProviderRequest) -> ProviderResponse:
        ...

    @abstractmethod
    def normalize_response(
        self,
        *,
        request: ProviderRequest,
        payload: dict | None,
        technical_status: str,
        http_status: int | None,
        latency_ms: int | None,
    ) -> ProviderResponse:
        ...

    def supports(self, verifier_key: str, category: str) -> bool:
        capability = self.get_capabilities()
        verifier_match = verifier_key in capability.supported_verifier_keys
        category_match = not capability.supported_categories or category in capability.supported_categories
        return capability.enabled and verifier_match and category_match
