from __future__ import annotations

from .generic_http_json import GenericHttpJsonProvider


class IdentityHttpProvider(GenericHttpJsonProvider):
    def __init__(self, *, config, client):
        super().__init__(
            provider_key="identity_http",
            provider_label="Identity HTTP Provider",
            config=config,
            client=client,
            supported_verifier_keys=["identity_db"],
            supported_categories=["identity"],
            endpoint_path="/verify/identity",
        )
