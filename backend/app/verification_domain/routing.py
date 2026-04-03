from __future__ import annotations

from typing import Protocol

from ..verifier_providers import build_default_provider_registry
from .contracts import ExtractedCredential, VerifierRouteDecision


class VerifierRouter(Protocol):
    def route(self, credential: ExtractedCredential) -> VerifierRouteDecision:
        ...


class RuleBasedVerifierRouter:
    ROUTE_BY_CATEGORY = {
        "identity": ("identity_db", "Identity Database"),
        "address": ("address_check", "Address Check"),
        "passport": ("passport_db", "Passport Database"),
        "license": ("license_registry", "License Registry"),
        "academic": ("academic_registry", "Academic Registry"),
        "financial": ("financial_registry", "Financial Registry"),
        "tax": ("tax_authority", "Tax Authority"),
        "certificate": ("certificate_registry", "Certificate Registry"),
    }

    FALLBACKS_BY_CATEGORY = {
        "identity": ["manual_review"],
        "address": ["manual_review"],
        "passport": ["manual_review"],
        "license": ["manual_review"],
        "academic": ["manual_review"],
        "financial": ["manual_review"],
        "tax": ["manual_review"],
        "certificate": ["manual_review"],
        "unknown": ["manual_review"],
    }

    def __init__(self):
        self.provider_registry = build_default_provider_registry()

    def route(self, credential: ExtractedCredential) -> VerifierRouteDecision:
        if not credential.requires_verification:
            return VerifierRouteDecision(
                credential_id=credential.credential_id,
                selected_verifier_key="not_required",
                selected_verifier_label="No Verification Needed",
                route_reason=credential.verification_reason or "The deterministic planner marked this field as out of scope for direct verification.",
                fallback_verifiers=[],
                manual_review_recommended=False,
            )

        if credential.category in self.ROUTE_BY_CATEGORY:
            verifier_key, verifier_label = self.ROUTE_BY_CATEGORY[credential.category]
            provider = self.provider_registry.find_provider(
                verifier_key=verifier_key,
                category=credential.category,
            )
            if provider is None:
                return VerifierRouteDecision(
                    credential_id=credential.credential_id,
                    selected_verifier_key="manual_review",
                    selected_verifier_label="Manual Review",
                    route_reason=f"No enabled provider path or local fallback is available for category '{credential.category}'.",
                    fallback_verifiers=self.FALLBACKS_BY_CATEGORY.get(credential.category, ["manual_review"]),
                    manual_review_recommended=True,
                )

            capability = provider.get_capabilities()
            provider_note = (
                f"Enabled provider '{capability.provider_key}' will be attempted first."
                if provider.provider_key != "local_mock"
                else "No external provider is enabled, so the bounded local mock path will be used."
            )
            return VerifierRouteDecision(
                credential_id=credential.credential_id,
                selected_verifier_key=verifier_key,
                selected_verifier_label=verifier_label,
                route_reason=(
                    f"Category '{credential.category}' maps to verifier '{verifier_key}'. "
                    f"{provider_note}"
                ),
                fallback_verifiers=self.FALLBACKS_BY_CATEGORY.get(credential.category, ["manual_review"]),
                manual_review_recommended=provider.provider_key == "local_mock" and credential.category == "unknown",
            )

        return VerifierRouteDecision(
            credential_id=credential.credential_id,
            selected_verifier_key="manual_review",
            selected_verifier_label="Manual Review",
            route_reason="No deterministic external verifier is configured for this category yet.",
            fallback_verifiers=self.FALLBACKS_BY_CATEGORY["unknown"],
            manual_review_recommended=True,
        )
