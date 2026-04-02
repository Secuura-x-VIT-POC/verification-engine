from __future__ import annotations

from .entra_vc_mock import verify as entra_verify
from .vit_mock import verify as vit_verify


def call_connector(data: dict, connector: str = "vit_registry") -> dict:
    normalized = connector.lower()

    if normalized in {"vit", "vit_registry", "vit_registry_mock"}:
        return vit_verify(data).model_dump(mode="json")
    if normalized in {"vc", "entra", "entra_vc", "entra_vc_mock", "verified_id"}:
        return entra_verify(data).model_dump(mode="json")

    raise ValueError("Unknown connector")
