from __future__ import annotations

from datetime import datetime

from ..contracts import (
    AGENT_PHASE_PASS_A,
    AgentCredentialCandidate,
    AgentDocumentUnderstanding,
    AgentExplanationArtifact,
    AgentExplanationArtifactCollection,
    AgentRouteRecommendation,
    SessionAgentCredentialCandidateCollection,
    SessionAgentRouteRecommendationCollection,
)
from .base import AgentProvider


ROUTES_BY_CATEGORY = {
    "identity": ["identity_db"],
    "address": ["address_check"],
    "passport": ["passport_db"],
    "license": ["license_registry"],
    "academic": ["academic_registry"],
    "certificate": ["certificate_registry"],
    "financial": ["financial_registry"],
    "tax": ["tax_authority"],
    "unknown": ["manual_review"],
}

ENHANCED_CATEGORY_HINTS = {
    "address": ("residency", "residential", "mailing", "billing", "domicile", "locality"),
    "academic": ("marksheet", "matriculation", "hall ticket", "enrollment", "student record", "grade report"),
    "identity": ("person name", "legal name", "citizen", "applicant", "holder"),
    "passport": ("travel number", "travel doc", "passport"),
    "license": ("licence", "permit", "driver"),
    "certificate": ("award", "completion", "certification"),
    "financial": ("routing number", "bank reference", "statement"),
    "tax": ("taxpayer", "revenue", "pan", "vat", "gst", "ssn"),
}


class DeterministicProvider(AgentProvider):
    provider_key = "deterministic"

    def analyze_document(
        self,
        *,
        session_id: str,
        extraction_payload,
        minimized_extraction_payload,
        document_profile,
        credentials,
        prompt_text: str,
    ) -> AgentDocumentUnderstanding:
        categories = [credential.category for credential in credentials.credentials if credential.category]
        detected_sections = []
        if any(category in {"identity", "passport", "license", "address"} for category in categories):
            detected_sections.append("identity_section")
        if any(category in {"academic", "certificate"} for category in categories):
            detected_sections.extend(["issuer_section", "credential_section"])
        if any(category in {"financial", "tax"} for category in categories):
            detected_sections.append("financial_section")
        if not detected_sections:
            detected_sections.append("unstructured_section")

        confidence = 0.84 if document_profile.document_type != "unknown" else 0.58
        unknown_count = sum(1 for category in categories if category == "unknown")
        manual_review = document_profile.document_type == "unknown" or unknown_count >= max(1, len(categories) // 3)

        return AgentDocumentUnderstanding(
            session_id=session_id,
            document_type_guess=document_profile.document_type,
            document_family_guess=document_profile.document_family,
            confidence=round(confidence, 2),
            detected_sections=detected_sections,
            detected_entities=[
                {
                    "label": credential.label,
                    "category": credential.category,
                    "credential_id": credential.credential_id,
                }
                for credential in credentials.credentials[:12]
            ],
            pii_signals=[
                credential.label
                for credential in credentials.credentials
                if credential.is_pii
            ],
            credential_candidates=[],
            reasoning_summary=(
                "Deterministic agent understanding used extracted labels, categories, and document profile "
                "to summarize likely document structure without altering extracted values."
            ),
            manual_review_recommended=manual_review,
        )

    def group_credentials(
        self,
        *,
        session_id: str,
        extraction_payload,
        document_understanding: AgentDocumentUnderstanding,
        document_profile,
        credentials,
        verification_plan,
        prompt_text: str,
    ) -> SessionAgentCredentialCandidateCollection:
        candidates = []
        for credential in credentials.credentials:
            inferred_category = _infer_category_from_credential(credential)
            candidate_category = inferred_category or credential.category
            ambiguity_flags = []
            if credential.category == "unknown" and candidate_category == "unknown":
                ambiguity_flags.append("UNKNOWN_CATEGORY")
            if credential.confidence is not None and credential.confidence < 0.7:
                ambiguity_flags.append("LOW_EXTRACTION_CONFIDENCE")

            candidates.append(
                AgentCredentialCandidate(
                    candidate_id=f"candidate-{credential.credential_id}",
                    label=credential.label,
                    category=candidate_category,
                    source_fields=[credential.label],
                    grouped_field_ids=[credential.credential_id],
                    grouped_values={credential.label: credential.normalized_value or credential.value},
                    confidence=round(float(credential.confidence or 0.6), 2),
                    verification_recommended=credential.requires_verification or candidate_category != "unknown",
                    verification_reason=(
                        credential.verification_reason
                        or "Agent-assisted grouping identified this field as a verification candidate."
                    ),
                    possible_verifier_keys=list(ROUTES_BY_CATEGORY.get(candidate_category, ["manual_review"])),
                    ambiguity_flags=ambiguity_flags,
                )
            )

        grouped_candidates = _build_group_candidates(credentials)
        candidates.extend(grouped_candidates)
        document_understanding.credential_candidates = [candidate.candidate_id for candidate in candidates]

        return SessionAgentCredentialCandidateCollection(
            session_id=session_id,
            document_type=document_profile.document_type,
            candidates=candidates,
        )

    def recommend_routes(
        self,
        *,
        session_id: str,
        document_understanding: AgentDocumentUnderstanding,
        credential_candidates: SessionAgentCredentialCandidateCollection,
        verification_plan,
        prompt_text: str,
    ) -> SessionAgentRouteRecommendationCollection:
        recommendations = []
        for candidate in credential_candidates.candidates:
            verifier_options = list(candidate.possible_verifier_keys or ["manual_review"])
            recommended_verifier = verifier_options[0]
            alternatives = verifier_options[1:]
            confidence = round(float(candidate.confidence or 0.55), 2)
            manual_review = recommended_verifier == "manual_review" or bool(candidate.ambiguity_flags)

            recommendations.append(
                AgentRouteRecommendation(
                    candidate_id=candidate.candidate_id,
                    recommended_verifier_key=recommended_verifier,
                    alternative_verifier_keys=alternatives,
                    route_reason=(
                        f"Agent-assisted grouping mapped '{candidate.label}' to category '{candidate.category}' "
                        f"and recommends '{recommended_verifier}'."
                        + (
                            " Microsoft Entra Verified ID is the preferred VC trust rail for this category when enabled."
                            if candidate.category in {"identity", "academic", "certificate"}
                            else ""
                        )
                    ),
                    confidence=confidence,
                    manual_review_recommended=manual_review,
                )
            )

        return SessionAgentRouteRecommendationCollection(
            session_id=session_id,
            document_type=verification_plan.document_type,
            recommendations=recommendations,
        )

    def generate_explanations(
        self,
        *,
        phase: str,
        session_id: str,
        document_understanding: AgentDocumentUnderstanding,
        credential_candidates: SessionAgentCredentialCandidateCollection,
        route_recommendations: SessionAgentRouteRecommendationCollection,
        document_profile,
        credentials,
        verification_plan,
        verification_task_results,
        credential_bundles,
        credential_audits,
        prompt_text: str,
    ) -> AgentExplanationArtifactCollection:
        explanations = [
            AgentExplanationArtifact(
                target_type="document",
                target_id=session_id,
                explanation_kind="document_understanding",
                summary=document_understanding.reasoning_summary,
                structured_reasons=[
                    f"document_type:{document_understanding.document_type_guess}",
                    f"document_family:{document_understanding.document_family_guess}",
                ],
                caution_notes=(
                    ["Manual review recommended for document understanding."]
                    if document_understanding.manual_review_recommended
                    else []
                ),
                generated_at=datetime.utcnow(),
            )
        ]

        if phase == AGENT_PHASE_PASS_A:
            for recommendation in route_recommendations.recommendations:
                explanations.append(
                    AgentExplanationArtifact(
                        target_type="candidate",
                        target_id=recommendation.candidate_id,
                        explanation_kind="route_support",
                        summary=recommendation.route_reason,
                        structured_reasons=[recommendation.recommended_verifier_key],
                        caution_notes=(
                            ["Manual review is still recommended."]
                            if recommendation.manual_review_recommended
                            else []
                        ),
                        generated_at=datetime.utcnow(),
                    )
                )
            return AgentExplanationArtifactCollection(
                session_id=session_id,
                document_type=document_profile.document_type,
                explanations=explanations,
            )

        bundle_lookup = {
            bundle.credential_id: bundle
            for bundle in getattr(credential_bundles, "bundles", [])
        }
        for audit in getattr(credential_audits, "audits", []):
            bundle = bundle_lookup.get(audit.credential_id)
            caution_notes = []
            if bundle is not None and bundle.final_audit_status in {"PARTIAL", "UNVERIFIED", "MANUAL_REVIEW"}:
                caution_notes.append("Evidence remains incomplete or uncertain.")
            explanations.append(
                AgentExplanationArtifact(
                    target_type="credential",
                    target_id=audit.credential_id,
                    explanation_kind="audit_support",
                    summary=(
                        f"Agent-assisted explanation: '{audit.label}' is currently '{audit.audit_status.lower()}' "
                        f"based on the executed verifier evidence and the bounded verification plan."
                    ),
                    structured_reasons=list(audit.reason_codes or []),
                    caution_notes=caution_notes,
                    generated_at=datetime.utcnow(),
                )
            )

        return AgentExplanationArtifactCollection(
            session_id=session_id,
            document_type=document_profile.document_type,
            explanations=explanations,
        )


def _infer_category_from_credential(credential) -> str:
    if credential.category != "unknown":
        return credential.category

    haystack = " ".join(
        part.lower()
        for part in (
            credential.label,
            credential.normalized_value or "",
            credential.source_text or "",
        )
        if part
    )
    for category, hints in ENHANCED_CATEGORY_HINTS.items():
        if any(hint in haystack for hint in hints):
            return category
    return "unknown"


def _build_group_candidates(credentials) -> list[AgentCredentialCandidate]:
    grouped = []
    academic_fields = [
        credential for credential in credentials.credentials
        if credential.category == "academic"
    ]
    identity_fields = [
        credential for credential in credentials.credentials
        if credential.category in {"identity", "passport", "license"}
    ]

    if len(academic_fields) >= 2:
        grouped.append(
            AgentCredentialCandidate(
                candidate_id="candidate-academic-bundle",
                label="Academic credential bundle",
                category="academic",
                source_fields=[credential.label for credential in academic_fields],
                grouped_field_ids=[credential.credential_id for credential in academic_fields],
                grouped_values={
                    credential.label: credential.normalized_value or credential.value
                    for credential in academic_fields
                },
                confidence=round(_average_confidence(academic_fields), 2),
                verification_recommended=True,
                verification_reason="Grouped academic signals suggest a single registry-backed verification path.",
                possible_verifier_keys=["academic_registry", "manual_review"],
                ambiguity_flags=[],
            )
        )

    if len(identity_fields) >= 2:
        grouped.append(
            AgentCredentialCandidate(
                candidate_id="candidate-identity-bundle",
                label="Identity evidence bundle",
                category="identity",
                source_fields=[credential.label for credential in identity_fields],
                grouped_field_ids=[credential.credential_id for credential in identity_fields],
                grouped_values={
                    credential.label: credential.normalized_value or credential.value
                    for credential in identity_fields
                },
                confidence=round(_average_confidence(identity_fields), 2),
                verification_recommended=True,
                verification_reason=(
                    "Grouped identity fields strengthen the need for bounded identity verification, "
                    "with Microsoft Entra Verified ID preferred when that trust rail is enabled."
                ),
                possible_verifier_keys=["identity_db", "manual_review"],
                ambiguity_flags=[],
            )
        )

    return grouped


def _average_confidence(credentials) -> float:
    values = [float(credential.confidence) for credential in credentials if credential.confidence is not None]
    if not values:
        return 0.6
    return sum(values) / len(values)
