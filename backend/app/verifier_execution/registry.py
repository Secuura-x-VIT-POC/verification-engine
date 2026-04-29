from __future__ import annotations

from typing import Protocol

from .verifiers import (
    AcademicRegistryVerifier,
    AddressCheckVerifier,
    CertificateRegistryVerifier,
    FinancialRegistryVerifier,
    IdentityDatabaseVerifier,
    LicenseRegistryVerifier,
    ManualReviewVerifier,
    PassportDatabaseVerifier,
    TaxAuthorityVerifier,
)


class RegisteredVerifier(Protocol):
    verifier_key: str
    verifier_label: str


class VerifierRegistry:
    def __init__(self):
        self._verifiers: dict[str, RegisteredVerifier] = {}

    def register(self, verifier: RegisteredVerifier) -> None:
        self._verifiers[verifier.verifier_key] = verifier

    def get(self, verifier_key: str):
        return self._verifiers.get(verifier_key)

    def all_keys(self) -> list[str]:
        return sorted(self._verifiers.keys())


def build_default_verifier_registry() -> VerifierRegistry:
    registry = VerifierRegistry()

    identity = IdentityDatabaseVerifier()
    academic = AcademicRegistryVerifier()
    address = AddressCheckVerifier()
    passport = PassportDatabaseVerifier()
    certificate = CertificateRegistryVerifier()
    license_v = LicenseRegistryVerifier()
    financial = FinancialRegistryVerifier()
    tax = TaxAuthorityVerifier()
    manual = ManualReviewVerifier()

    for verifier in (
        identity,
        address,
        passport,
        academic,
        certificate,
        license_v,
        financial,
        tax,
        manual,
    ):
        registry.register(verifier)

    registry._verifiers["entra_verified_id"] = identity
    registry._verifiers["local_mock_registry"] = academic

    return registry