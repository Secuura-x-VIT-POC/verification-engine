from __future__ import annotations

from typing import Any

from .contracts import DemoProfileSummary, DemoProviderFixture


DEMO_PROFILE_ACADEMIC = "academic_transcript_demo"
DEMO_PROFILE_CERTIFICATE = "certificate_partial_demo"
DEMO_PROFILE_IDENTITY = "identity_mismatch_demo"
DEMO_PROFILE_MIXED = "mixed_manual_review_demo"


_PROFILE_DEFINITIONS = {
    DEMO_PROFILE_ACADEMIC: {
        "label": "Academic transcript demo",
        "description": (
            "Seeded academic-verification scenario with Entra-preferred VC verification, "
            "verified identity and issuer fields, and partial evidence for identifier fields."
        ),
        "scenario_family": "academic_document",
        "notes": [
            "Microsoft Entra Verified ID is shown as the primary trust rail in demo-mock mode.",
            "Institution and credential fields resolve to verified or partial states deterministically.",
        ],
    },
    DEMO_PROFILE_CERTIFICATE: {
        "label": "Certificate partial demo",
        "description": (
            "Seeded certificate-verification scenario with partial registry evidence and "
            "missing supporting claims highlighted honestly."
        ),
        "scenario_family": "certificate_document",
        "notes": [
            "Certificate fields surface partial match behavior for presentation.",
            "Supplementary registry providers remain available behind the same provider framework.",
        ],
    },
    DEMO_PROFILE_IDENTITY: {
        "label": "Identity mismatch demo",
        "description": (
            "Seeded identity-verification scenario that demonstrates contradiction handling and "
            "red mismatch outcomes without claiming live provider evidence."
        ),
        "scenario_family": "identity_document",
        "notes": [
            "Identity-oriented claims return deterministic mismatch evidence for presentation.",
            "Manual review remains available when a mismatch should not auto-resolve the document outcome.",
        ],
    },
    DEMO_PROFILE_MIXED: {
        "label": "Mixed manual-review demo",
        "description": (
            "Seeded mixed-document scenario that emphasizes honest manual-review fallbacks for "
            "credentials without an executable verification path."
        ),
        "scenario_family": "mixed_document",
        "notes": [
            "Used when the document family is mixed or cannot be mapped cleanly to a stronger seeded scenario.",
            "No successful live-provider claim is implied in this profile.",
        ],
    },
}


def resolve_demo_profile_key(
    *,
    document_type: str | None,
    explicit_key: str | None = None,
) -> str:
    candidate = str(explicit_key or "").strip()
    if candidate in _PROFILE_DEFINITIONS:
        return candidate

    normalized_document_type = str(document_type or "unknown").lower()
    if any(token in normalized_document_type for token in ("certificate", "badge")):
        return DEMO_PROFILE_CERTIFICATE
    if any(token in normalized_document_type for token in ("identity", "passport", "license")):
        return DEMO_PROFILE_IDENTITY
    if any(token in normalized_document_type for token in ("academic", "transcript", "credential")):
        return DEMO_PROFILE_ACADEMIC
    return DEMO_PROFILE_MIXED


def build_demo_profile_summary(
    *,
    session_id: str,
    provider_operating_mode: str,
    document_type: str | None,
    explicit_key: str | None = None,
) -> DemoProfileSummary:
    profile_key = resolve_demo_profile_key(
        document_type=document_type,
        explicit_key=explicit_key,
    )
    definition = _PROFILE_DEFINITIONS[profile_key]
    return DemoProfileSummary(
        session_id=session_id,
        profile_key=profile_key,
        profile_label=definition["label"],
        description=definition["description"],
        scenario_family=definition["scenario_family"],
        provider_operating_mode=provider_operating_mode,
        seeded=True,
        notes=list(definition["notes"]),
    )


def build_demo_provider_fixture(
    *,
    provider_key: str,
    provider_label: str,
    verifier_key: str,
    input_payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    profile_key: str,
) -> DemoProviderFixture:
    payload = dict(input_payload or {})
    meta = dict(metadata or {})
    category = str(meta.get("category") or payload.get("category") or "").lower()
    label = str(payload.get("label") or verifier_key or "credential").strip()
    value = payload.get("value")
    field_key = _resolve_field_key(label=label, category=category, verifier_key=verifier_key)

    resolved_profile_key = resolve_demo_profile_key(
        document_type=str(payload.get("document_type") or meta.get("document_type") or category or "unknown"),
        explicit_key=profile_key,
    )

    if resolved_profile_key == DEMO_PROFILE_IDENTITY:
        fixture = _build_identity_mismatch_fixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            field_key=field_key,
            value=value,
        )
    elif resolved_profile_key == DEMO_PROFILE_CERTIFICATE:
        fixture = _build_certificate_partial_fixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            field_key=field_key,
            value=value,
            category=category,
        )
    elif resolved_profile_key == DEMO_PROFILE_MIXED:
        fixture = _build_mixed_manual_review_fixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            field_key=field_key,
            value=value,
        )
    else:
        fixture = _build_academic_demo_fixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            field_key=field_key,
            value=value,
            category=category,
        )

    response_summary = dict(fixture.response_summary or {})
    response_summary.setdefault("demo_profile_key", resolved_profile_key)
    response_summary.setdefault("demo_profile_label", _PROFILE_DEFINITIONS[resolved_profile_key]["label"])
    response_summary.setdefault("mock_mode", True)
    response_summary.setdefault("live_execution", False)
    response_summary.setdefault("provider_key", provider_key)
    response_summary.setdefault("provider_label", provider_label)
    return fixture.model_copy(update={"response_summary": response_summary})


def _build_academic_demo_fixture(
    *,
    provider_key: str,
    provider_label: str,
    verifier_key: str,
    field_key: str,
    value: Any,
    category: str,
) -> DemoProviderFixture:
    value_text = _as_text(value)
    if provider_key == "entra_verified_id" and (
        category in {"identity", "academic", "certificate"} or field_key in {"name", "institution", "credential"}
    ):
        if field_key in {"document_id", "issue_date"}:
            return DemoProviderFixture(
                provider_key=provider_key,
                provider_label=provider_label,
                verifier_key=verifier_key,
                scenario_status="partial",
                matched_fields={"credential_context": "Academic credential presentation accepted"},
                missing_fields=[field_key],
                confidence=0.82,
                reason_codes=["DEMO_ENTRA_PARTIAL", "DEMO_ACADEMIC_TRANSCRIPT"],
                response_summary={
                    "trust_rail": "Microsoft Entra Verified ID",
                    "presentation_state": "partial",
                    "scenario_case": "academic_partial_identifier",
                    "note": "The seeded demo scenario keeps identifier/date fields amber when supporting VC claims are absent.",
                },
                latency_ms=42,
            )
        return DemoProviderFixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            scenario_status="verified",
            matched_fields={field_key: value_text or f"demo-{field_key}"},
            confidence=0.94,
            reason_codes=["DEMO_ENTRA_VERIFIED", "DEMO_ACADEMIC_TRANSCRIPT"],
            response_summary={
                "trust_rail": "Microsoft Entra Verified ID",
                "presentation_state": "verified",
                "scenario_case": "academic_verified_claim",
                "note": "Seeded Entra-aligned presentation verification was used for this demo run.",
            },
            latency_ms=38,
        )

    if provider_key == "academic_registry_http":
        return DemoProviderFixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            scenario_status="partial",
            matched_fields={field_key: value_text or f"demo-{field_key}"},
            missing_fields=["registry_issue_date"],
            confidence=0.79,
            reason_codes=["DEMO_SUPPLEMENTARY_PARTIAL", "DEMO_ACADEMIC_TRANSCRIPT"],
            response_summary={
                "scenario_case": "academic_registry_partial",
                "note": "Supplementary academic registry evidence is seeded for presentation but does not replace the Entra-first rail.",
            },
            latency_ms=57,
        )

    return _build_mixed_manual_review_fixture(
        provider_key=provider_key,
        provider_label=provider_label,
        verifier_key=verifier_key,
        field_key=field_key,
        value=value,
    )


def _build_certificate_partial_fixture(
    *,
    provider_key: str,
    provider_label: str,
    verifier_key: str,
    field_key: str,
    value: Any,
    category: str,
) -> DemoProviderFixture:
    value_text = _as_text(value)
    if provider_key == "entra_verified_id" and category in {"certificate", "academic", "identity"}:
        return DemoProviderFixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            scenario_status="partial",
            matched_fields={field_key: value_text or f"demo-{field_key}"},
            missing_fields=["issuer_attestation", "presentation_expiry"],
            confidence=0.77,
            reason_codes=["DEMO_ENTRA_PARTIAL", "DEMO_CERTIFICATE_SCENARIO"],
            response_summary={
                "trust_rail": "Microsoft Entra Verified ID",
                "presentation_state": "partial",
                "scenario_case": "certificate_partial",
                "note": "Seeded certificate presentation is accepted, but issuer and expiry claims remain incomplete.",
            },
            latency_ms=46,
        )

    if provider_key == "academic_registry_http":
        return DemoProviderFixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            scenario_status="partial",
            matched_fields={field_key: value_text or f"demo-{field_key}"},
            missing_fields=["registry_backing_record"],
            confidence=0.71,
            reason_codes=["DEMO_SUPPLEMENTARY_PARTIAL", "DEMO_CERTIFICATE_SCENARIO"],
            response_summary={
                "scenario_case": "certificate_registry_partial",
                "note": "Supplementary registry evidence is seeded for certificate lookup in demo mode.",
            },
            latency_ms=63,
        )

    return _build_mixed_manual_review_fixture(
        provider_key=provider_key,
        provider_label=provider_label,
        verifier_key=verifier_key,
        field_key=field_key,
        value=value,
    )


def _build_identity_mismatch_fixture(
    *,
    provider_key: str,
    provider_label: str,
    verifier_key: str,
    field_key: str,
    value: Any,
) -> DemoProviderFixture:
    mismatched_value = _demo_mismatch_value(value)
    if provider_key in {"entra_verified_id", "identity_http"}:
        return DemoProviderFixture(
            provider_key=provider_key,
            provider_label=provider_label,
            verifier_key=verifier_key,
            scenario_status="mismatch",
            mismatched_fields={field_key: mismatched_value},
            confidence=0.93,
            reason_codes=["DEMO_IDENTITY_MISMATCH", "DEMO_MISMATCH_SCENARIO"],
            response_summary={
                "trust_rail": (
                    "Microsoft Entra Verified ID"
                    if provider_key == "entra_verified_id"
                    else "Supplementary identity registry"
                ),
                "presentation_state": "contradicted",
                "scenario_case": "identity_mismatch",
                "note": "Seeded mismatch output is being used for presentation. This is not a live provider result.",
            },
            latency_ms=44,
        )

    return _build_mixed_manual_review_fixture(
        provider_key=provider_key,
        provider_label=provider_label,
        verifier_key=verifier_key,
        field_key=field_key,
        value=value,
    )


def _build_mixed_manual_review_fixture(
    *,
    provider_key: str,
    provider_label: str,
    verifier_key: str,
    field_key: str,
    value: Any,
) -> DemoProviderFixture:
    del value
    return DemoProviderFixture(
        provider_key=provider_key,
        provider_label=provider_label,
        verifier_key=verifier_key,
        scenario_status="manual_review",
        missing_fields=[field_key],
        confidence=0.58,
        reason_codes=["DEMO_MANUAL_REVIEW", "DEMO_MIXED_SCENARIO"],
        response_summary={
            "scenario_case": "manual_review",
            "note": "No stronger seeded verification path exists for this credential in the current demo profile.",
        },
        manual_review_recommended=True,
        latency_ms=29,
    )


def _resolve_field_key(*, label: str, category: str, verifier_key: str) -> str:
    normalized_label = label.lower()
    if "name" in normalized_label:
        return "name"
    if "institution" in normalized_label or "issuer" in normalized_label:
        return "institution"
    if "credential" in normalized_label or "degree" in normalized_label or category in {"academic", "certificate"}:
        return "credential"
    if "date" in normalized_label:
        return "issue_date"
    if "id" in normalized_label or "identifier" in normalized_label:
        return "document_id"
    if category == "identity":
        return "name"
    if category == "address":
        return "address"
    return verifier_key


def _demo_mismatch_value(value: Any) -> str:
    text = _as_text(value)
    if text:
        return f"{text} [demo mismatch]"
    return "demo-mismatched-value"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
