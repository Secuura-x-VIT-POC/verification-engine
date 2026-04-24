from __future__ import annotations

from statistics import mean

from .schemas import FieldDecision, FinalVerdict, VerifierResult


def clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def fuse_confidence(
    *,
    extraction_confidence: float,
    ai_confidence: float,
    verification_confidence: float,
    grounding_confidence: float,
) -> float:
    score = (
        0.40 * clamp_confidence(extraction_confidence)
        + 0.25 * clamp_confidence(ai_confidence)
        + 0.25 * clamp_confidence(verification_confidence)
        + 0.10 * clamp_confidence(grounding_confidence)
    )
    return clamp_confidence(score)


def determine_field_decision(
    *,
    field_id: str,
    label: str,
    extracted_value: str,
    normalized_value: str,
    extraction_confidence: float,
    ai_confidence: float,
    grounding_confidence: float,
    verifier_result: VerifierResult | None,
    mandatory: bool,
    unsafe_or_malformed: bool,
) -> FieldDecision:
    verification_confidence = verifier_result.verification_confidence if verifier_result else 0.0
    final_confidence = fuse_confidence(
        extraction_confidence=extraction_confidence,
        ai_confidence=ai_confidence,
        verification_confidence=verification_confidence,
        grounding_confidence=grounding_confidence,
    )
    reason_codes: list[str] = []
    status = "AMBER"
    source_api = verifier_result.source_api if verifier_result else None
    audit_message = "Field requires reviewer attention."

    if unsafe_or_malformed:
        status = "RED"
        reason_codes.append("UNSAFE_OR_MALFORMED_DOCUMENT")
        audit_message = "Document safety validation raised a hard failure."
    elif verifier_result and verifier_result.status == "MISMATCH":
        status = "RED"
        reason_codes.extend(verifier_result.reason_codes or ["CRITICAL_VERIFIER_MISMATCH"])
        audit_message = verifier_result.audit_message or "Verifier reported a critical mismatch."
    elif verifier_result and any(code in {"REVOKED_CREDENTIAL", "INVALID_CREDENTIAL"} for code in verifier_result.reason_codes):
        status = "RED"
        reason_codes.extend(verifier_result.reason_codes)
        audit_message = verifier_result.audit_message or "Verifier reported an invalid credential."
    elif mandatory and not str(normalized_value or extracted_value).strip():
        status = "RED"
        reason_codes.append("MANDATORY_FIELD_MISSING")
        audit_message = "Mandatory field is missing from the extracted document."
    elif verifier_result and verifier_result.status == "TIMEOUT" and verifier_result.high_assurance:
        status = "RED"
        reason_codes.extend(verifier_result.reason_codes or ["REQUIRED_HIGH_ASSURANCE_TIMEOUT"])
        audit_message = verifier_result.audit_message or "Required high-assurance verifier timed out."
    elif verifier_result and verifier_result.status in {"TIMEOUT", "ERROR"} and verifier_result.optional:
        status = "AMBER"
        reason_codes.extend(verifier_result.reason_codes or ["OPTIONAL_VERIFIER_UNAVAILABLE"])
        audit_message = verifier_result.audit_message or "Optional verifier was unavailable."
    elif verifier_result and verifier_result.status == "VERIFIED" and final_confidence >= 0.75 and grounding_confidence >= 0.5:
        status = "GREEN"
        reason_codes.extend(verifier_result.reason_codes or ["VERIFIER_CONFIRMED"])
        audit_message = verifier_result.audit_message or "Verifier confirmed the extracted claim."
    elif ai_confidence < 0.45:
        status = "AMBER"
        reason_codes.append("LOW_AI_CONFIDENCE")
        audit_message = "AI confidence was low without a hard contradiction."
    elif final_confidence >= 0.8 and (not mandatory or verification_confidence >= 0.5 or source_api is None):
        status = "GREEN"
        reason_codes.append("HIGH_COMPOSITE_CONFIDENCE")
        audit_message = "Composite confidence met the acceptance threshold."
    elif final_confidence < 0.45:
        status = "RED" if mandatory else "AMBER"
        reason_codes.append("LOW_COMPOSITE_CONFIDENCE")
        audit_message = "Composite confidence was below the acceptance threshold."
    else:
        reason_codes.append("REVIEW_RECOMMENDED")

    return FieldDecision(
        field_id=field_id,
        label=label,
        extracted_value=extracted_value or "",
        normalized_value=normalized_value or extracted_value or "",
        status=status,
        ai_confidence=ai_confidence,
        extraction_confidence=extraction_confidence,
        verification_confidence=verification_confidence,
        grounding_confidence=grounding_confidence,
        final_confidence=final_confidence,
        reason_codes=list(dict.fromkeys(reason_codes or ["REVIEW_RECOMMENDED"])),
        source_api=source_api,
        audit_message=audit_message,
        bounding_boxes=[],
    )


def build_final_verdict(
    *,
    field_decisions: list[FieldDecision],
    verifier_results: list[VerifierResult],
    unsafe_or_malformed: bool,
    document_reason_codes: list[str] | None = None,
) -> FinalVerdict:
    red_fields = [field for field in field_decisions if field.status == "RED"]
    amber_fields = [field for field in field_decisions if field.status == "AMBER"]
    hard_red_verifier = next(
        (
            result
            for result in verifier_results
            if result.status == "MISMATCH"
            or any(code in {"REVOKED_CREDENTIAL", "INVALID_CREDENTIAL"} for code in result.reason_codes)
            or (result.status == "TIMEOUT" and result.high_assurance)
        ),
        None,
    )
    connector_ids = sorted({result.connector_id for result in verifier_results if result.connector_id})
    reason_codes = list(document_reason_codes or [])

    if unsafe_or_malformed:
        outcome = "RED"
        reason_codes.append("UNSAFE_OR_MALFORMED_DOCUMENT")
        explanation = "Document safety checks produced a hard failure."
    elif hard_red_verifier is not None:
        outcome = "RED"
        reason_codes.extend(hard_red_verifier.reason_codes or ["CRITICAL_VERIFIER_MISMATCH"])
        explanation = hard_red_verifier.audit_message or "A verifier returned a hard failure."
    elif red_fields:
        outcome = "RED"
        reason_codes.extend(code for field in red_fields for code in field.reason_codes)
        explanation = "One or more critical fields failed verification policy."
    elif field_decisions and all(field.status == "GREEN" for field in field_decisions):
        outcome = "GREEN"
        reason_codes.append("ALL_MANDATORY_FIELDS_VERIFIED")
        explanation = "All mandatory fields were verified and no contradictions were found."
    else:
        outcome = "AMBER"
        reason_codes.extend(code for field in amber_fields for code in field.reason_codes)
        if not amber_fields:
            reason_codes.append("REVIEW_RECOMMENDED")
        explanation = "The document requires reviewer attention but no hard failure was detected."

    matching_score = mean(field.final_confidence for field in field_decisions) if field_decisions else 0.0
    visual_match_probability = mean(field.grounding_confidence for field in field_decisions) if field_decisions else 0.0
    risk_level = "HIGH" if outcome == "RED" else "MEDIUM" if outcome == "AMBER" else "LOW"

    return FinalVerdict(
        outcome=outcome,
        reason_codes=list(dict.fromkeys(reason_codes)),
        connector_ids=connector_ids,
        explanation=explanation,
        risk_level=risk_level,
        matching_score=matching_score,
        visual_match_probability=visual_match_probability,
    )
