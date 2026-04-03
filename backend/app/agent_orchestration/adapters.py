from __future__ import annotations

from typing import Any

from ..verifier_providers import build_default_provider_registry
from ..verification_domain.routing import preferred_provider_for_category
from ..verification_domain.contracts import EvidenceItem


VERIFIER_LABELS = {
    "identity_db": "Identity Database",
    "address_check": "Address Check",
    "passport_db": "Passport Database",
    "license_registry": "License Registry",
    "academic_registry": "Academic Registry",
    "certificate_registry": "Certificate Registry",
    "financial_registry": "Financial Registry",
    "tax_authority": "Tax Authority",
    "manual_review": "Manual Review",
}

PROVIDER_LABELS = {
    "entra_verified_id": "Microsoft Entra Verified ID",
    "identity_http": "Supplementary Identity HTTP Provider",
    "academic_registry_http": "Supplementary Academic Registry HTTP Provider",
    "local_mock": "Local Mock Provider",
}

PII_CATEGORIES = {"identity", "address", "passport", "license", "financial", "tax"}
PROVIDER_REGISTRY = build_default_provider_registry()


def apply_agent_enrichment_to_credentials(
    credentials,
    credential_candidates,
    *,
    classification_override_confidence: float,
):
    candidate_by_field_id = {}
    for candidate in getattr(credential_candidates, "candidates", []):
        if len(candidate.grouped_field_ids) != 1:
            continue
        credential_id = candidate.grouped_field_ids[0]
        current = candidate_by_field_id.get(credential_id)
        if current is None or float(candidate.confidence or 0.0) > float(current.confidence or 0.0):
            candidate_by_field_id[credential_id] = candidate

    enriched_credentials = []
    for credential in credentials.credentials:
        candidate = candidate_by_field_id.get(credential.credential_id)
        if candidate is None:
            enriched_credentials.append(_copy_model(credential))
            continue

        updates: dict[str, Any] = {}
        candidate_confidence = float(candidate.confidence or 0.0)
        if (
            credential.category == "unknown"
            and candidate.category != "unknown"
            and candidate_confidence >= classification_override_confidence
        ):
            updates["category"] = candidate.category
            updates["verification_reason"] = (
                f"{credential.verification_reason or 'No baseline verification reason.'} "
                f"Agent-assisted classification suggests category '{candidate.category}'."
            ).strip()
        if (
            not credential.requires_verification
            and candidate.verification_recommended
            and candidate.category != "unknown"
            and candidate_confidence >= classification_override_confidence
        ):
            updates["requires_verification"] = True
            updates["verification_reason"] = (
                candidate.verification_reason
                or f"Agent-assisted grouping recommends verifying this '{candidate.category}' field."
            )
        if updates.get("category", credential.category) in PII_CATEGORIES and not credential.is_pii:
            updates["is_pii"] = True

        enriched_credentials.append(_copy_model(credential, updates=updates))

    return _copy_model(credentials, updates={"credentials": enriched_credentials})


def apply_agent_enrichment_to_document_profile(
    document_profile,
    document_understanding,
    *,
    classification_override_confidence: float,
):
    updates: dict[str, Any] = {}
    confidence = float(document_understanding.confidence or 0.0)
    if (
        document_profile.document_type == "unknown"
        and document_understanding.document_type_guess != "unknown"
        and confidence >= classification_override_confidence
    ):
        updates["document_type"] = document_understanding.document_type_guess
    if (
        document_profile.document_family == "unknown"
        and document_understanding.document_family_guess != "unknown"
        and confidence >= classification_override_confidence
    ):
        updates["document_family"] = document_understanding.document_family_guess

    notes = list(document_profile.notes or [])
    notes.append(f"Agent-assisted summary: {document_understanding.reasoning_summary}")
    updates["notes"] = _dedupe(notes)
    updates["requires_manual_review"] = (
        document_profile.requires_manual_review or document_understanding.manual_review_recommended
    )
    return _copy_model(document_profile, updates=updates)


def apply_agent_enrichment_to_verification_plan(
    verification_plan,
    credentials,
    credential_candidates,
    route_recommendations,
    *,
    route_override_confidence: float,
):
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in getattr(credential_candidates, "candidates", [])
    }
    recommendations_by_field: dict[str, Any] = {}
    for recommendation in getattr(route_recommendations, "recommendations", []):
        candidate = candidates_by_id.get(recommendation.candidate_id)
        if candidate is None:
            continue
        for credential_id in candidate.grouped_field_ids:
            current = recommendations_by_field.get(credential_id)
            if current is None or float(recommendation.confidence or 0.0) > float(current[1].confidence or 0.0):
                recommendations_by_field[credential_id] = (candidate, recommendation)

    decisions = []
    tasks_by_id = {task.credential_id: task for task in verification_plan.tasks}
    tasks = []

    for decision in verification_plan.route_decisions:
        copied_decision = _copy_model(decision)
        copied_task = tasks_by_id.get(decision.credential_id)
        copied_task = _copy_model(copied_task) if copied_task is not None else None
        agent_pair = recommendations_by_field.get(decision.credential_id)
        if agent_pair is not None:
            candidate, recommendation = agent_pair
            copied_decision, copied_task = _apply_route_recommendation(
                copied_decision,
                copied_task,
                candidate,
                recommendation,
                route_override_confidence=route_override_confidence,
            )

        decisions.append(copied_decision)
        if copied_task is not None:
            tasks.append(copied_task)

    return _copy_model(
        verification_plan,
        updates={
            "route_decisions": decisions,
            "tasks": tasks,
        },
    )


def merge_agent_explanations_into_audits(credential_audits, explanations):
    explanation_map = {
        explanation.target_id: explanation
        for explanation in getattr(explanations, "explanations", [])
        if explanation.target_type == "credential"
    }
    merged = []
    for audit in credential_audits.audits:
        explanation = explanation_map.get(audit.credential_id)
        if explanation is None:
            merged.append(_copy_model(audit))
            continue

        evidence = list(audit.evidence or [])
        evidence.append(
            EvidenceItem(
                evidence_type="agent_explanation",
                source="agent_orchestration",
                detail={
                    "summary": explanation.summary,
                    "structured_reasons": explanation.structured_reasons,
                    "caution_notes": explanation.caution_notes,
                    "generated_at": explanation.generated_at.isoformat() if explanation.generated_at else None,
                },
            )
        )
        merged.append(
            _copy_model(
                audit,
                updates={
                    "explanation": f"{audit.explanation} Agent-assisted note: {explanation.summary}",
                    "reason_codes": _dedupe(list(audit.reason_codes or []) + list(explanation.structured_reasons or [])),
                    "evidence": evidence,
                },
            )
        )

    return _copy_model(credential_audits, updates={"audits": merged})


def _apply_route_recommendation(
    decision,
    task,
    candidate,
    recommendation,
    *,
    route_override_confidence: float,
):
    confidence = float(recommendation.confidence or 0.0)
    assistant_payload = {
        "candidate_id": candidate.candidate_id,
        "grouped_field_ids": list(candidate.grouped_field_ids),
        "recommended_verifier_key": recommendation.recommended_verifier_key,
        "alternative_verifier_keys": list(recommendation.alternative_verifier_keys),
        "route_reason": recommendation.route_reason,
        "confidence": recommendation.confidence,
        "manual_review_recommended": recommendation.manual_review_recommended,
    }

    route_reason_suffix = f" Agent-assisted note: {recommendation.route_reason}"
    if route_reason_suffix not in decision.route_reason:
        decision.route_reason = f"{decision.route_reason}{route_reason_suffix}".strip()

    provider_available = PROVIDER_REGISTRY.find_provider(
        verifier_key=recommendation.recommended_verifier_key,
        category=candidate.category,
    ) is not None

    should_override = (
        decision.selected_verifier_key == "manual_review"
        and recommendation.recommended_verifier_key != "manual_review"
        and confidence >= route_override_confidence
        and provider_available
    )
    if should_override:
        decision.selected_verifier_key = recommendation.recommended_verifier_key
        decision.selected_verifier_label = VERIFIER_LABELS.get(
            recommendation.recommended_verifier_key,
            recommendation.recommended_verifier_key.replace("_", " ").title(),
        )
        decision.manual_review_recommended = recommendation.manual_review_recommended

    preferred_provider_key, preferred_provider_label = preferred_provider_for_category(candidate.category)
    planned_provider = PROVIDER_REGISTRY.find_provider(
        verifier_key=decision.selected_verifier_key,
        category=candidate.category,
        preferred_provider_key=preferred_provider_key,
    )
    decision.preferred_provider_key = preferred_provider_key
    decision.preferred_provider_label = preferred_provider_label
    decision.planned_provider_key = planned_provider.provider_key if planned_provider is not None else None
    decision.planned_provider_label = (
        PROVIDER_LABELS.get(planned_provider.provider_key, planned_provider.provider_key.replace("_", " ").title())
        if planned_provider is not None
        else None
    )

    if task is not None:
        task.input_payload = dict(task.input_payload or {})
        task.input_payload["agent_assisted"] = assistant_payload
        task.input_payload["preferred_provider_key"] = decision.preferred_provider_key
        task.input_payload["preferred_provider_label"] = decision.preferred_provider_label
        task.input_payload["planned_provider_key"] = decision.planned_provider_key
        task.input_payload["planned_provider_label"] = decision.planned_provider_label
        task.reason_codes = _dedupe(list(task.reason_codes or []) + ["AGENT_ASSISTED"])
        if len(candidate.grouped_field_ids) > 1:
            task.reason_codes = _dedupe(list(task.reason_codes or []) + ["AGENT_GROUPED_CREDENTIAL"])
        if should_override:
            task.verifier_key = decision.selected_verifier_key
            task.verifier_label = decision.selected_verifier_label
            task.status = "PLANNED"
            task.reason_codes = _dedupe(list(task.reason_codes or []) + ["AGENT_ROUTE_ASSISTED"])
        elif recommendation.recommended_verifier_key != decision.selected_verifier_key:
            task.reason_codes = _dedupe(list(task.reason_codes or []) + ["AGENT_ROUTE_CONFLICT"])
        else:
            task.reason_codes = _dedupe(list(task.reason_codes or []) + ["AGENT_ROUTE_ALIGNED"])
        if not provider_available and recommendation.recommended_verifier_key != "manual_review":
            task.reason_codes = _dedupe(list(task.reason_codes or []) + ["AGENT_ROUTE_PROVIDER_UNAVAILABLE"])

    return decision, task


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _copy_model(model, *, updates: dict[str, Any] | None = None):
    if hasattr(model, "model_copy"):
        return model.model_copy(deep=True, update=updates or {})
    return model.copy(deep=True, update=updates or {})
