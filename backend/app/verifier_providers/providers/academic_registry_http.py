from __future__ import annotations

from .generic_http_json import GenericHttpJsonProvider


class AcademicRegistryHttpProvider(GenericHttpJsonProvider):
    def __init__(self, *, config, client):
        super().__init__(
            provider_key="academic_registry_http",
            provider_label="Supplementary Academic Registry HTTP Provider",
            config=config,
            client=client,
            supported_verifier_keys=["academic_registry"],
            supported_categories=["academic", "certificate"],
            endpoint_path="/verify/academic",
        )
