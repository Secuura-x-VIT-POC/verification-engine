from __future__ import annotations

from typing import Any
from ..agent_orchestration.schemas import FieldDecision, VerifierResult, FinalVerdict

def determine_field_decision(
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
    """
    Evaluates a single field. Hard policy overrides execute first. 
    Linear confidence fusion is only applied if no critical failures occur.
    """
    reason_codes: list[str] = []
    source_api = verifier_result.connector_id if verifier_result else None
    audit_message = verifier_result.audit_message if verifier_result else "No external verifier evidence provided."
    verification_confidence = verifier_result.verification_confidence if verifier_result else 0.0

    # ---------------------------------------------------------
    # 1. HARD POLICY OVERRIDES (Short-circuit the math)
    # ---------------------------------------------------------
    
    if unsafe_or_malformed:
        return _build_decision(
            field_id, label, extracted_value, normalized_value, "RED", 0.0,
            extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
            ["UNSAFE_DOCUMENT"], source_api, "Document flagged as unsafe or malformed."
        )

    if mandatory and not str(extracted_value or "").strip():
        return _build_decision(
            field_id, label, extracted_value, normalized_value, "RED", 0.0,
            extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
            ["MISSING_MANDATORY_FIELD"], source_api, "Mandatory field is missing from extraction."
        )

    if verifier_result:
        # Critical mismatch: External evidence contradicts the document
        if verifier_result.status == "MISMATCH":
            return _build_decision(
                field_id, label, extracted_value, normalized_value, "RED", 0.0,
                extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
                verifier_result.reason_codes or ["VERIFIER_MISMATCH"], source_api, audit_message
            )
        
        # Mandatory verifier timeout after retries
        if verifier_result.status == "TIMEOUT":
            if verifier_result.high_assurance:
                return _build_decision(
                    field_id, label, extracted_value, normalized_value, "RED", 0.0,
                    extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
                    verifier_result.reason_codes or ["MANDATORY_VERIFIER_TIMEOUT"], source_api, audit_message
                )
            else:
                return _build_decision(
                    field_id, label, extracted_value, normalized_value, "AMBER", verification_confidence,
                    extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
                    verifier_result.reason_codes or ["OPTIONAL_VERIFIER_TIMEOUT"], source_api, audit_message
                )
        
        # API Error (Internal or remote)
        if verifier_result.status == "ERROR":
            status = "RED" if verifier_result.high_assurance else "AMBER"
            return _build_decision(
                field_id, label, extracted_value, normalized_value, status, verification_confidence,
                extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
                verifier_result.reason_codes or ["VERIFIER_ERROR"], source_api, audit_message
            )

    # ---------------------------------------------------------
    # 2. CONFIDENCE FUSION MATH (Demo defaults)
    # ---------------------------------------------------------
    
    final_confidence = (
        (0.40 * extraction_confidence) +
        (0.25 * ai_confidence) +
        (0.25 * verification_confidence) +
        (0.10 * grounding_confidence)
    )

    # ---------------------------------------------------------
    # 3. SCORE THRESHOLDING
    # ---------------------------------------------------------
    
    if final_confidence >= 0.80:
        status = "GREEN"
        if not verifier_result or verifier_result.status == "SKIPPED":
            reason_codes.append("UNVERIFIED_HIGH_CONFIDENCE")
    elif final_confidence >= 0.40:
        status = "AMBER"
        reason_codes.append("LOW_CONFIDENCE_REVIEW_REQUIRED")
    else:
        status = "RED"
        reason_codes.append("INSUFFICIENT_CONFIDENCE")

    return _build_decision(
        field_id, label, extracted_value, normalized_value, status, final_confidence,
        extraction_confidence, ai_confidence, verification_confidence, grounding_confidence,
        reason_codes, source_api, audit_message
    )

def _build_decision(
    field_id: str, label: str, extracted_value: str, normalized_value: str,
    status: str, final_confidence: float, extraction_confidence: float,
    ai_confidence: float, verification_confidence: float, grounding_confidence: float,
    reason_codes: list[str], source_api: str | None, audit_message: str
) -> FieldDecision:
    """Helper to instantiate the Pydantic model cleanly."""
    return FieldDecision(
        field_id=field_id,
        label=label,
        extracted_value=extracted_value,
        normalized_value=normalized_value,
        status=status,  # type: ignore
        final_confidence=final_confidence,
        extraction_confidence=extraction_confidence,
        ai_confidence=ai_confidence,
        verification_confidence=verification_confidence,
        grounding_confidence=grounding_confidence,
        reason_codes=reason_codes,
        source_api=source_api,
        audit_message=audit_message,
        bounding_boxes=[] # Bounding boxes are attached back in graph.py
    )

def build_final_verdict(
    field_decisions: list[FieldDecision],
    verifier_results: list[VerifierResult],
    unsafe_or_malformed: bool,
    document_reason_codes: list[str],
) -> FinalVerdict:
    """
    Rolls up field-level decisions into a single document-level verdict.
    A single critical RED field makes the entire document RED.
    """
    reasons = list(document_reason_codes)
    connector_ids = list({v.connector_id for v in verifier_results if v.connector_id})
    
    if unsafe_or_malformed:
        reasons.append("UNSAFE_DOCUMENT")
        return FinalVerdict(
            outcome="RED",
            reason_codes=reasons,
            connector_ids=connector_ids,
            explanation="Document cannot be processed safely due to malware or malformed PDF structure.",
            risk_level="HIGH"
        )

    has_red = any(f.status == "RED" for f in field_decisions)
    has_amber = any(f.status == "AMBER" for f in field_decisions)
    
    # Accumulate all non-green reason codes for the final audit trail
    for field in field_decisions:
        if field.status != "GREEN":
            reasons.extend(field.reason_codes)
            
    # Deduplicate reason codes to keep the UI clean
    reasons = list(dict.fromkeys(reasons))
    
    # Document-level aggregation [cite: 108, 109]
    if has_red:
        return FinalVerdict(
            outcome="RED",
            reason_codes=reasons,
            connector_ids=connector_ids,
            explanation="Critical mismatch found between document fields and verifier sources, or mandatory evidence failed.",
            risk_level="HIGH"
        )
    elif has_amber:
        return FinalVerdict(
            outcome="AMBER",
            reason_codes=reasons,
            connector_ids=connector_ids,
            explanation="Document requires manual review due to ambiguous extraction, low AI confidence, or missing optional verifiers.",
            risk_level="MEDIUM"
        )
    else:
        return FinalVerdict(
            outcome="GREEN",
            reason_codes=reasons,
            connector_ids=connector_ids,
            explanation="All mandatory claims are grounded, verified, and not contradicted.",
            risk_level="LOW"
        )


def evaluate_trust(trust_input: dict, verifier_results: list[dict], policy: dict) -> dict:
    """
    Evaluates the overall trust for a document based on field extractions, verifier results, and policy.
    """
    verifier_map = {}

    for vr in verifier_results:
        field_id = vr.get("credential_id") or vr.get("field_id") or "unknown"

        task_status = vr.get("task_status")

        if task_status == "SUCCEEDED":
            status = "VERIFIED"
        elif task_status == "FAILED":
            status = "MISMATCH"
        elif task_status == "MANUAL_REVIEW":
            status = "ERROR"
        elif task_status == "PARTIAL":
            status = "ERROR"
        else:
            status = "ERROR"

        verifier_map[field_id] = VerifierResult(
            task_id=vr.get("task_id", ""),
            field_id=field_id,
            connector_id=vr.get("executed_provider_key"),
            status=status,
            verification_confidence=vr.get("confidence") or 0.5,
            reason_codes=vr.get("reason_codes", []),
            high_assurance=(vr.get("assurance_required") == "HIGH"),
        )
    
    field_decisions = []
    
    for field_id, value in trust_input["fields"].items():
        confidence = trust_input["confidence"].get(field_id, 0.0)
        mandatory = field_id in policy.get("required_fields", [])
        
        extracted_value = value
        normalized_value = value
        extraction_confidence = confidence
        ai_confidence = confidence
        grounding_confidence = 1.0  # Placeholder, adjust as needed
        
        vr = verifier_map.get(field_id)

        decision = determine_field_decision(
            field_id,
            field_id,
            extracted_value,
            normalized_value,
            extraction_confidence,
            ai_confidence,
            grounding_confidence,
            vr,
            mandatory,
            False,
        )
        field_decisions.append(decision)
    
    final_verdict = build_final_verdict(field_decisions, list(verifier_map.values()), False, [])
    return final_verdict.model_dump()