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


def evaluate_trust(trust_input: dict, connector_result: dict | list[dict] | None, policy: dict) -> dict:
    """
    Evaluates the overall trust for a document based on field extractions, verifier results, and policy.
    """
    normalized_verifier_results = _normalize_verifier_results(connector_result)
    verifier_by_field = {
        result.field_id: result
        for result in normalized_verifier_results
        if result.field_id and result.field_id != "dummy"
    }
    primary_verifier_result = normalized_verifier_results[0] if normalized_verifier_results else None

    field_decisions = []
    fields = _normalize_trust_fields(trust_input, policy)

    for field_id, field in fields.items():
        value = field["value"]
        confidence = field["confidence"]
        mandatory = field["mandatory"]
        
        extracted_value = value
        normalized_value = value
        extraction_confidence = confidence
        ai_confidence = confidence
        grounding_confidence = 1.0  # Placeholder, adjust as needed
        
        decision = determine_field_decision(
            field_id, field_id, extracted_value, normalized_value,
            extraction_confidence, ai_confidence, grounding_confidence,
            verifier_by_field.get(field_id) or primary_verifier_result, mandatory, False
        )
        field_decisions.append(decision)
    
    final_verdict = build_final_verdict(field_decisions, normalized_verifier_results, False, [])
    return final_verdict.model_dump()


def _normalize_verifier_results(connector_result: dict | list[dict] | None) -> list[VerifierResult]:
    verifier_results: list[VerifierResult] = []
    for item in _normalize_connector_results(connector_result):
        if "task_status" in item or "audit_status" in item or "executed_provider_key" in item:
            verifier_results.append(_verifier_result_from_task_result(item))
            continue
        status, malformed = _normalize_provider_status(item.get("status"))
        confidence, confidence_malformed = _safe_float(
            item.get("verification_confidence"),
            default=1.0 if not malformed else 0.0,
        )
        reason_codes = list(item.get("reason_codes") or [])
        if malformed or confidence_malformed:
            reason_codes = list(dict.fromkeys([*reason_codes, "PROVIDER_RESULT_MALFORMED"]))
        verifier_results.append(
            VerifierResult(
                task_id=str(item.get("task_id") or "connector"),
                field_id=str(item.get("field_id") or "dummy"),
                connector_id=str(item.get("connector_id") or item.get("provider_key") or "provider"),
                status=status,
                verification_confidence=confidence,
                reason_codes=reason_codes,
                high_assurance=item.get("assurance_class") == "HIGH",
            )
        )
    return verifier_results


def _verifier_result_from_task_result(item: dict[str, Any]) -> VerifierResult:
    audit_status = str(item.get("audit_status") or "").upper()
    task_status = str(item.get("task_status") or "").upper()
    if audit_status == "VERIFIED":
        status = "VERIFIED"
        confidence, confidence_malformed = _safe_float(item.get("confidence"), default=0.95)
    elif audit_status == "MISMATCH":
        status = "MISMATCH"
        confidence, confidence_malformed = _safe_float(item.get("confidence"), default=0.0)
    elif task_status == "SKIPPED":
        status = "SKIPPED"
        confidence, confidence_malformed = _safe_float(item.get("confidence"), default=0.0)
    elif "TIMEOUT" in set(item.get("reason_codes") or []):
        status = "TIMEOUT"
        confidence, confidence_malformed = _safe_float(item.get("confidence"), default=0.2)
    else:
        status = "ERROR"
        confidence, confidence_malformed = _safe_float(item.get("confidence"), default=0.35)

    connector_id = (
        item.get("executed_provider_key")
        or item.get("planned_provider_key")
        or item.get("verifier_key")
        or "provider"
    )
    reason_codes = list(item.get("reason_codes") or [])
    if confidence_malformed:
        reason_codes = list(dict.fromkeys([*reason_codes, "PROVIDER_RESULT_MALFORMED"]))
    return VerifierResult(
        task_id=str(item.get("task_id") or ""),
        field_id=str(item.get("credential_id") or item.get("field_id") or "dummy"),
        connector_id=str(connector_id),
        status=status,
        verification_confidence=float(confidence or 0.0),
        reason_codes=reason_codes,
        source_api=str(connector_id),
        audit_message=str(item.get("explanation") or ""),
        high_assurance=item.get("planned_provider_key") == "entra_verified_id",
    )


def _normalize_connector_results(connector_result: dict | list[dict] | None) -> list[dict]:
    if isinstance(connector_result, dict):
        return [connector_result]
    if isinstance(connector_result, list):
        return [item for item in connector_result if isinstance(item, dict)]
    return []


def _normalize_provider_status(value: Any) -> tuple[str, bool]:
    normalized = str(value or "").upper()
    allowed = {"VERIFIED", "MISMATCH", "TIMEOUT", "ERROR", "SKIPPED", "NOT_APPLICABLE"}
    if normalized in allowed:
        return normalized, False
    return "ERROR", True


def _safe_float(value: Any, *, default: float) -> tuple[float, bool]:
    if value in (None, ""):
        return float(default), False
    try:
        return float(value), False
    except (TypeError, ValueError):
        return 0.0, True


def _normalize_trust_fields(trust_input: dict, policy: dict) -> dict[str, dict[str, Any]]:
    required_fields = {str(item) for item in policy.get("required_fields", [])}
    raw_fields = trust_input.get("fields") or {}
    confidence_map = trust_input.get("confidence") or {}
    fields: dict[str, dict[str, Any]] = {}

    if isinstance(raw_fields, dict):
        for field_id, value in raw_fields.items():
            key = str(field_id)
            fields[key] = {
                "value": value,
                "confidence": float(confidence_map.get(key, 0.0) or 0.0),
                "mandatory": key in required_fields,
            }
    elif isinstance(raw_fields, list):
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            key = str(item.get("name") or item.get("field_id") or "")
            if not key:
                continue
            value = item.get("value")
            confidence = item.get("confidence")
            fields[key] = {
                "value": value or "",
                "confidence": float(confidence if confidence not in (None, "") else 0.0),
                "mandatory": bool(item.get("is_mandatory")) or key in required_fields,
            }

    for field_id in required_fields:
        fields.setdefault(field_id, {"value": "", "confidence": 0.0, "mandatory": True})
    return fields
