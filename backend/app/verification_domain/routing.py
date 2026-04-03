from __future__ import annotations

from typing import Protocol

from ..verifier_providers import (
    PROVIDER_OPERATING_MODE_DEMO_MOCK,
    PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED,
    PROVIDER_OPERATING_MODE_MANUAL_ONLY,
    build_default_provider_registry,
    load_provider_runtime_policy,
)
from .contracts import (
    FALLBACK_REASON_ENTRA_NOT_CONFIGURED,
    FALLBACK_REASON_LIVE_PROVIDER_DISABLED,
    FALLBACK_REASON_LOCAL_DEMO_VERIFICATION,
    FALLBACK_REASON_MANUAL_REVIEW_ONLY,
    FALLBACK_REASON_NO_EXECUTABLE_PROVIDER,
    FALLBACK_REASON_SUPPLEMENTARY_PROVIDER_USED,
    ExtractedCredential,
    VerifierRouteDecision,
)

ENTRA_VERIFIED_ID_PROVIDER_KEY = "entra_verified_id"
ENTRA_VERIFIED_ID_PROVIDER_LABEL = "Microsoft Entra Verified ID"
ENTRA_FIRST_CATEGORIES = {"identity", "academic", "certificate"}


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
        self.provider_policy = load_provider_runtime_policy()

    def route(self, credential: ExtractedCredential) -> VerifierRouteDecision:
        if not credential.requires_verification:
            return VerifierRouteDecision(
                credential_id=credential.credential_id,
                selected_verifier_key="not_required",
                selected_verifier_label="No Verification Needed",
                route_reason=credential.verification_reason or "The deterministic planner marked this field as out of scope for direct verification.",
                preferred_provider_key=None,
                preferred_provider_label=None,
                planned_provider_key=None,
                planned_provider_label=None,
                planned_execution_mode=None,
                planned_is_live_result=False,
                planned_is_mock_result=False,
                planned_is_demo_result=False,
                fallback_reason=None,
                fallback_verifiers=[],
                manual_review_recommended=False,
            )

        if credential.category in self.ROUTE_BY_CATEGORY:
            verifier_key, verifier_label = self.ROUTE_BY_CATEGORY[credential.category]
            preferred_provider_key, preferred_provider_label = preferred_provider_for_category(credential.category)
            provider = self.provider_registry.find_provider(
                verifier_key=verifier_key,
                category=credential.category,
                preferred_provider_key=preferred_provider_key,
            )
            if provider is None:
                fallback_reason = _resolve_no_provider_fallback_reason(
                    preferred_provider_key=preferred_provider_key,
                    provider_operating_mode=self.provider_policy.transition_config.provider_operating_mode,
                    provider_registry=self.provider_registry,
                    verifier_key=verifier_key,
                    category=credential.category,
                )
                route_reason = (
                    f"Category '{credential.category}' maps to verifier '{verifier_key}', but no executable provider path is enabled."
                )
                if preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY:
                    route_reason = (
                        f"Category '{credential.category}' is Entra-first, but {preferred_provider_label} is not executable "
                        "and no supplementary provider path is enabled."
                    )
                return VerifierRouteDecision(
                    credential_id=credential.credential_id,
                    selected_verifier_key="manual_review",
                    selected_verifier_label="Manual Review",
                    route_reason=route_reason,
                    preferred_provider_key=preferred_provider_key,
                    preferred_provider_label=preferred_provider_label,
                    planned_provider_key=None,
                    planned_provider_label=None,
                    planned_execution_mode="MANUAL_REVIEW",
                    planned_is_live_result=False,
                    planned_is_mock_result=False,
                    planned_is_demo_result=False,
                    fallback_reason=fallback_reason,
                    fallback_verifiers=self.FALLBACKS_BY_CATEGORY.get(credential.category, ["manual_review"]),
                    manual_review_recommended=True,
                )

            capability = provider.get_capabilities()
            planned_execution_mode = _resolve_planned_execution_mode(
                provider_key=provider.provider_key,
                provider_operating_mode=capability.operating_mode,
            )
            fallback_reason = _resolve_planned_fallback_reason(
                provider_key=provider.provider_key,
                provider_operating_mode=capability.operating_mode,
                preferred_provider_key=preferred_provider_key,
            )
            provider_note = _build_provider_note(
                credential_category=credential.category,
                provider_key=provider.provider_key,
                provider_label=capability.provider_label,
                preferred_provider_key=preferred_provider_key,
                preferred_provider_label=preferred_provider_label,
                planned_execution_mode=planned_execution_mode,
                fallback_reason=fallback_reason,
            )
            return VerifierRouteDecision(
                credential_id=credential.credential_id,
                selected_verifier_key=verifier_key,
                selected_verifier_label=verifier_label,
                route_reason=(
                    f"Category '{credential.category}' maps to verifier '{verifier_key}'. "
                    f"{provider_note}"
                ),
                preferred_provider_key=preferred_provider_key,
                preferred_provider_label=preferred_provider_label,
                planned_provider_key=provider.provider_key,
                planned_provider_label=capability.provider_label,
                planned_execution_mode=planned_execution_mode,
                planned_is_live_result=planned_execution_mode == "LIVE_PROVIDER",
                planned_is_mock_result=provider.provider_key == "local_mock",
                planned_is_demo_result=capability.operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK,
                fallback_reason=fallback_reason,
                fallback_verifiers=self.FALLBACKS_BY_CATEGORY.get(credential.category, ["manual_review"]),
                manual_review_recommended=provider.provider_key == "local_mock" and credential.category == "unknown",
            )

        return VerifierRouteDecision(
            credential_id=credential.credential_id,
            selected_verifier_key="manual_review",
            selected_verifier_label="Manual Review",
            route_reason="No deterministic external verifier is configured for this category yet.",
            preferred_provider_key=None,
            preferred_provider_label=None,
            planned_provider_key=None,
            planned_provider_label=None,
            planned_execution_mode="MANUAL_REVIEW",
            planned_is_live_result=False,
            planned_is_mock_result=False,
            planned_is_demo_result=False,
            fallback_reason=FALLBACK_REASON_NO_EXECUTABLE_PROVIDER,
            fallback_verifiers=self.FALLBACKS_BY_CATEGORY["unknown"],
            manual_review_recommended=True,
        )


def preferred_provider_for_category(category: str) -> tuple[str | None, str | None]:
    if category in ENTRA_FIRST_CATEGORIES:
        return ENTRA_VERIFIED_ID_PROVIDER_KEY, ENTRA_VERIFIED_ID_PROVIDER_LABEL
    return None, None


def _build_provider_note(
    *,
    credential_category: str,
    provider_key: str,
    provider_label: str,
    preferred_provider_key: str | None,
    preferred_provider_label: str | None,
    planned_execution_mode: str | None,
    fallback_reason: str | None,
) -> str:
    if preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY and provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY:
        if planned_execution_mode == "DEMO_PROVIDER":
            return (
                f"{preferred_provider_label} remains the preferred VC trust rail for category '{credential_category}', "
                "and this environment will run its seeded demo path rather than a live provider call."
            )
        return (
            f"{preferred_provider_label} is the primary VC trust rail for category '{credential_category}' and will be attempted first."
        )
    if preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY and provider_key == "local_mock":
        if fallback_reason == FALLBACK_REASON_LOCAL_DEMO_VERIFICATION:
            return (
                f"{preferred_provider_label} is the preferred VC trust rail for category '{credential_category}', "
                "but this environment is running in bounded demo mode and the local mock verifier will execute."
            )
        return (
            f"{preferred_provider_label} is the preferred VC trust rail for category '{credential_category}', "
            "but it is not enabled in this environment, so the bounded local mock path will be used."
        )
    if preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY:
        return (
            f"{preferred_provider_label} is preferred for category '{credential_category}', "
            f"but supplementary provider '{provider_label}' will be used in this environment."
        )
    if provider_key == "local_mock":
        if fallback_reason == FALLBACK_REASON_LOCAL_DEMO_VERIFICATION:
            return "This environment is running in bounded demo mode, so the local mock verifier will execute."
        return "No external provider is enabled, so the bounded local mock path will be used."
    return f"Enabled provider '{provider_label}' will be attempted first."


def _resolve_planned_execution_mode(*, provider_key: str, provider_operating_mode: str) -> str:
    if provider_key == "local_mock":
        return "LOCAL_MOCK"
    if provider_operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
        return "DEMO_PROVIDER"
    if provider_operating_mode == PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        return "LIVE_PROVIDER"
    return "PROVIDER"


def _resolve_planned_fallback_reason(
    *,
    provider_key: str,
    provider_operating_mode: str,
    preferred_provider_key: str | None,
) -> str | None:
    if provider_key == "local_mock" and provider_operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK:
        return FALLBACK_REASON_LOCAL_DEMO_VERIFICATION
    if preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY and provider_key == "local_mock":
        return FALLBACK_REASON_ENTRA_NOT_CONFIGURED
    if preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY and provider_key != ENTRA_VERIFIED_ID_PROVIDER_KEY:
        return FALLBACK_REASON_SUPPLEMENTARY_PROVIDER_USED
    if provider_key == "local_mock" and provider_operating_mode != PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        return FALLBACK_REASON_LIVE_PROVIDER_DISABLED
    return None


def _resolve_no_provider_fallback_reason(
    *,
    preferred_provider_key: str | None,
    provider_operating_mode: str,
    provider_registry,
    verifier_key: str,
    category: str,
) -> str:
    if provider_operating_mode == PROVIDER_OPERATING_MODE_MANUAL_ONLY:
        return FALLBACK_REASON_MANUAL_REVIEW_ONLY
    if (
        preferred_provider_key == ENTRA_VERIFIED_ID_PROVIDER_KEY
        and _preferred_provider_not_executable(
            provider_registry=provider_registry,
            preferred_provider_key=preferred_provider_key,
            verifier_key=verifier_key,
            category=category,
        )
    ):
        return FALLBACK_REASON_ENTRA_NOT_CONFIGURED
    if provider_operating_mode != PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED:
        return FALLBACK_REASON_LIVE_PROVIDER_DISABLED
    return FALLBACK_REASON_NO_EXECUTABLE_PROVIDER


def _preferred_provider_not_executable(*, provider_registry, preferred_provider_key: str, verifier_key: str, category: str) -> bool:
    preferred = provider_registry.get(preferred_provider_key)
    if preferred is None:
        return True
    return not preferred.supports(verifier_key, category)
