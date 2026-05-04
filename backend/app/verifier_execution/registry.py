from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..verifier_providers import (
    PROVIDER_OPERATING_MODE_DEMO_MOCK,
    PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
    PROVIDER_OPERATING_MODE_MANUAL_ONLY,
    build_default_provider_registry,
    load_provider_runtime_policy,
)
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


PROVIDER_ALIASES = {
    "local_mock_registry": "local_mock",
    "manual_review_provider": "manual_review",
}

CLAIM_TYPE_TO_VERIFIER = {
    "identity": "identity_db",
    "person_name": "identity_db",
    "document_identifier": "identity_db",
    "document_id": "identity_db",
    "identity_document": "identity_db",
    "issuer_authenticity": "academic_registry",
    "organization": "academic_registry",
    "institution": "academic_registry",
    "academic": "academic_registry",
    "credential": "academic_registry",
    "qualification": "academic_registry",
    "academic_degree": "academic_registry",
    "academic_credential": "academic_registry",
    "date_validity": "certificate_registry",
    "issue_date": "certificate_registry",
    "expiry_date": "certificate_registry",
    "certificate": "certificate_registry",
    "certificate_document": "certificate_registry",
    "address": "address_check",
    "location": "address_check",
    "passport": "passport_db",
    "license": "license_registry",
    "financial": "financial_registry",
    "monetary_amount": "financial_registry",
    "amount": "financial_registry",
    "tax": "tax_authority",
    "status": "manual_review",
    "result": "manual_review",
    "eligibility": "manual_review",
}

CLAIM_TYPE_TO_CATEGORY = {
    "academic_degree": "academic",
    "academic_credential": "academic",
    "credential": "academic",
    "qualification": "academic",
    "certificate_document": "certificate",
    "identity_document": "identity",
    "person_name": "identity",
    "document_identifier": "identity",
    "document_id": "identity",
    "issuer_authenticity": "academic",
    "organization": "academic",
    "institution": "academic",
    "date_validity": "certificate",
    "issue_date": "certificate",
    "expiry_date": "certificate",
    "location": "address",
    "monetary_amount": "financial",
    "amount": "financial",
}


@dataclass(frozen=True)
class ProviderCandidate:
    provider_key: str
    provider_label: str
    verifier_key: str
    reason_codes: list[str] = field(default_factory=list)
    fallback_reason: str | None = None


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

    def verifier_key_for_claim_type(self, claim_type: str) -> str:
        return CLAIM_TYPE_TO_VERIFIER.get(_canonical_claim_type(claim_type), "manual_review")

    def get_provider_candidates(
        self,
        *,
        claim_type: str,
        required_fields: list[str] | None = None,
        assurance_required: str = "MEDIUM",
        context: dict[str, Any] | None = None,
    ) -> list[ProviderCandidate]:
        del required_fields
        provider_policy = load_provider_runtime_policy()
        provider_registry = build_default_provider_registry()
        normalized_claim_type = _canonical_claim_type(claim_type)
        verifier_key = self.verifier_key_for_claim_type(normalized_claim_type)
        category = _category_for_claim_type(normalized_claim_type, context)
        preferred_provider_key = _preferred_provider_for_assurance(
            assurance_required=assurance_required,
            verifier_key=verifier_key,
        )
        candidates: list[ProviderCandidate] = []

        if provider_policy.transition_config.provider_operating_mode == PROVIDER_OPERATING_MODE_MANUAL_ONLY:
            manual = self.get("manual_review")
            return [
                ProviderCandidate(
                    provider_key="manual_review",
                    provider_label=getattr(manual, "verifier_label", "Manual Review"),
                    verifier_key="manual_review",
                    reason_codes=["MANUAL_REVIEW_ONLY", "MANUAL_REVIEW_FALLBACK"],
                    fallback_reason="MANUAL_REVIEW_ONLY",
                )
            ]

        if verifier_key != "manual_review":
            ordered_capabilities = provider_registry.all_capabilities()
            if preferred_provider_key:
                ordered_capabilities = sorted(
                    ordered_capabilities,
                    key=lambda capability: 0 if capability.provider_key == preferred_provider_key else 1,
                )
            for capability in ordered_capabilities:
                provider = provider_registry.get(capability.provider_key)
                if provider is None or not provider.supports(verifier_key, category):
                    continue
                reason_codes = [
                    f"CLAIM_TYPE_{_reason_token(normalized_claim_type)}",
                    f"PROVIDER_SUPPORTS_{_reason_token(category)}",
                ]
                fallback_reason = None
                if capability.provider_key == "local_mock":
                    reason_codes.append("SAFE_LOCAL_FALLBACK_CANDIDATE")
                    fallback_reason = (
                        "LOCAL_DEMO_VERIFICATION"
                        if capability.operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK
                        else "LIVE_PROVIDER_DISABLED"
                    )
                elif capability.operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
                    reason_codes.append("EXTERNAL_PROVIDER_CONFIGURED")
                candidates.append(
                    ProviderCandidate(
                        provider_key=capability.provider_key,
                        provider_label=capability.provider_label,
                        verifier_key=verifier_key,
                        reason_codes=reason_codes,
                        fallback_reason=fallback_reason,
                    )
                )

        if not candidates:
            manual = self.get("manual_review")
            candidates.append(
                ProviderCandidate(
                    provider_key="manual_review",
                    provider_label=getattr(manual, "verifier_label", "Manual Review"),
                    verifier_key="manual_review",
                    reason_codes=["NO_PROVIDER_AVAILABLE", "MANUAL_REVIEW_FALLBACK"],
                    fallback_reason="NO_EXECUTABLE_PROVIDER",
                )
            )
        return candidates


def build_default_verifier_registry() -> VerifierRegistry:
    registry = VerifierRegistry()
    for verifier in (
        IdentityDatabaseVerifier(),
        AddressCheckVerifier(),
        PassportDatabaseVerifier(),
        AcademicRegistryVerifier(),
        CertificateRegistryVerifier(),
        LicenseRegistryVerifier(),
        FinancialRegistryVerifier(),
        TaxAuthorityVerifier(),
        ManualReviewVerifier(),
    ):
        registry.register(verifier)
    return registry


def canonical_provider_key(provider_key: str | None) -> str:
    normalized = str(provider_key or "").strip()
    return PROVIDER_ALIASES.get(normalized, normalized)


def _category_for_claim_type(claim_type: str, context: dict[str, Any] | None) -> str:
    if context:
        explicit = str(context.get("category") or "").strip().lower()
        if explicit:
            return explicit
    normalized = _canonical_claim_type(claim_type)
    return CLAIM_TYPE_TO_CATEGORY.get(normalized, normalized or "unknown")


def _canonical_claim_type(claim_type: str | None) -> str:
    normalized = str(claim_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "name": "person_name",
        "id": "document_identifier",
        "issuer": "issuer_authenticity",
        "credential_title": "credential",
        "degree": "credential",
        "date": "date_validity",
        "address_location": "address",
        "money": "monetary_amount",
    }
    return aliases.get(normalized, normalized)


def _preferred_provider_for_assurance(*, assurance_required: str, verifier_key: str) -> str | None:
    if verifier_key in {"identity_db", "academic_registry", "certificate_registry"}:
        return "entra_verified_id"
    if str(assurance_required or "").upper() == "HIGH":
        return "entra_verified_id"
    return None


def _reason_token(value: str) -> str:
    token = "".join(character if character.isalnum() else "_" for character in str(value or "").upper())
    return token.strip("_") or "UNKNOWN"
