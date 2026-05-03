from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..agent_orchestration.schemas import FinalVerdict


ClaimFindingStatus = Literal["GREEN", "AMBER", "RED"]

MANUAL_REVIEW_REASON_CODES = {
    "AI_ONLY_EVIDENCE",
    "ALL_PROVIDERS_FAILED",
    "LOW_CONFIDENCE_REVIEW_REQUIRED",
    "LOW_CONFIDENCE",
    "MANUAL_REVIEW_PROVIDER_SELECTED",
    "MANUAL_REVIEW_REQUIRED",
    "MISSING_CREDENTIAL_REFERENCE",
    "NO_EXECUTABLE_PROVIDER",
    "NO_PROVIDER_AVAILABLE",
    "NO_TASK_RESULT",
    "NO_VERIFIER_EVIDENCE",
    "PROVIDER_CAPABILITY_MISMATCH",
    "PROVIDER_RESULT_MALFORMED",
    "PROVIDER_NOT_REGISTERED",
    "PROVIDER_UNAVAILABLE",
    "REQUIRED_CLAIM_MISSING",
    "UNAVAILABLE_VERIFIER",
    "VERIFIER_NOT_REGISTERED",
}

REASON_CODE_ALIASES = {
    "CONNECTOR_MISMATCH": "PROVIDER_MISMATCH",
    "CRITICAL_VERIFIER_MISMATCH": "PROVIDER_MISMATCH",
    "FIELD_LEVEL_EVIDENCE_INSUFFICIENT": "NO_VERIFIER_EVIDENCE",
    "LOW_CONFIDENCE_REVIEW_REQUIRED": "LOW_CONFIDENCE",
    "MANUAL_REVIEW_RECOMMENDED": "MANUAL_REVIEW_REQUIRED",
    "NO_CONNECTOR_EVIDENCE": "NO_VERIFIER_EVIDENCE",
    "OPTIONAL_VERIFIER_UNAVAILABLE": "PROVIDER_UNAVAILABLE",
    "PROVIDER_VERIFIED": "VERIFIED_BY_PROVIDER",
    "REGISTRY_MATCH": "VERIFIED_BY_PROVIDER",
    "REGISTRY_MATCHED": "VERIFIED_BY_PROVIDER",
    "VERIFIER_EVIDENCE_MATCHED": "VERIFIED_BY_PROVIDER",
    "VERIFIER_EXECUTION_FAILED": "PROVIDER_UNAVAILABLE",
    "VERIFIER_MISMATCH": "PROVIDER_MISMATCH",
}

REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


class ClaimFindingConfidence(BaseModel):
    ai: float = 0.0
    verifier: float = 0.0
    final: float = 0.0

    _confidence_fields = field_validator("ai", "verifier", "final", mode="before")(
        lambda cls, value: _clamp(value)
    )


class ClaimFinding(BaseModel):
    finding_id: str
    claim_id: str
    credential_id: str
    field_id: str | None = None
    label: str
    claim_type: str = "generic_claim"
    status: ClaimFindingStatus
    confidence: ClaimFindingConfidence = Field(default_factory=ClaimFindingConfidence)
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str = ""
    source_provider_id: str | None = None
    source_provider_label: str | None = None
    verifier_refs: list[str] = Field(default_factory=list)
    manual_review_required: bool = False
    bounding_boxes: list[dict[str, Any]] = Field(default_factory=list)


class TrustFindingCounts(BaseModel):
    green: int = 0
    amber: int = 0
    red: int = 0


class TrustFindingsResult(BaseModel):
    overall_outcome: ClaimFindingStatus
    final_verdict: FinalVerdict
    claim_findings: list[ClaimFinding] = Field(default_factory=list)
    finding_counts: TrustFindingCounts = Field(default_factory=TrustFindingCounts)
    reason_codes: list[str] = Field(default_factory=list)
    verifier_backed_evidence: bool = False


def build_claim_findings_from_execution(
    *,
    claims: list[Any],
    task_results: list[Any] | None = None,
    required_claim_ids: list[str] | None = None,
) -> TrustFindingsResult:
    return build_trust_findings(
        claims=claims,
        task_results=task_results,
        required_claim_ids=required_claim_ids,
    )


def normalize_reason_codes(reason_codes: Any) -> list[str]:
    return _safe_reason_codes(reason_codes)


def build_trust_findings(
    *,
    claims: list[Any],
    task_results: list[Any] | None = None,
    required_claim_ids: list[str] | None = None,
) -> TrustFindingsResult:
    safe_claims = [_as_dict(claim) for claim in claims]
    safe_results = [_as_dict(result) for result in (task_results or [])]
    results_by_claim = _index_results_by_claim(safe_results)
    required_ids = set(required_claim_ids or [])
    if not required_ids:
        required_ids = {
            _claim_key(claim)
            for claim in safe_claims
            if bool(claim.get("requires_verification", True))
        }

    findings = [
        _build_claim_finding(
            claim=claim,
            result=_best_result_for_claim(claim, results_by_claim, safe_results),
        )
        for claim in safe_claims
    ]
    findings.extend(_missing_required_findings(required_ids, findings))

    return _build_result(findings=findings, required_claim_ids=required_ids)


def _build_claim_finding(*, claim: dict[str, Any], result: dict[str, Any] | None) -> ClaimFinding:
    claim_id = str(claim.get("claim_id") or claim.get("credential_id") or claim.get("field_id") or "")
    credential_id = str(claim.get("credential_id") or claim_id)
    missing_required_claim = _is_required_claim_missing(claim)
    evidence_result = None if missing_required_claim else result
    status, default_reasons = _status_and_reasons(claim, evidence_result)
    explicit_reasons = _dedupe(
        [
            *_safe_reason_codes(claim.get("reason_codes")),
            *_safe_reason_codes(evidence_result.get("reason_codes") if evidence_result else []),
        ]
    )
    if evidence_result is None or missing_required_claim:
        reason_codes = _dedupe([*explicit_reasons, *default_reasons])
    else:
        reason_codes = explicit_reasons or _dedupe(default_reasons)
    provider_id = _safe_string(
        _first_present(
            evidence_result,
            "executed_provider_key",
            "planned_provider_key",
            "preferred_provider_key",
            "connector_id",
            "provider_id",
            "verifier_key",
        )
    )
    provider_label = _safe_string(
        _first_present(
            evidence_result,
            "executed_provider_label",
            "planned_provider_label",
            "preferred_provider_label",
            "verifier_label",
        )
    )
    verifier_refs = [str(evidence_result["task_id"])] if evidence_result and evidence_result.get("task_id") else []
    ai_confidence = _clamp(
        _first_present(claim, "ai_confidence", "confidence", "extraction_confidence")
    )
    verifier_confidence = _clamp(evidence_result.get("confidence") if evidence_result else 0.0)
    if evidence_result and "confidence" not in evidence_result:
        verifier_confidence = _clamp(evidence_result.get("verification_confidence"))
    final_confidence = verifier_confidence if evidence_result else min(ai_confidence, 0.79)

    return ClaimFinding(
        finding_id=f"finding-{claim_id or credential_id}",
        claim_id=claim_id or credential_id,
        credential_id=credential_id,
        field_id=_safe_string(claim.get("field_id")),
        label=_safe_string(claim.get("label") or claim.get("canonical_label") or "Claim") or "Claim",
        claim_type=_safe_string(claim.get("claim_type") or "generic_claim") or "generic_claim",
        status=status,
        confidence=ClaimFindingConfidence(
            ai=ai_confidence,
            verifier=verifier_confidence,
            final=final_confidence,
        ),
        reason_codes=reason_codes,
        explanation=_safe_explanation(status, evidence_result),
        source_provider_id=provider_id,
        source_provider_label=provider_label,
        verifier_refs=verifier_refs,
        manual_review_required=_requires_manual_review(status, reason_codes, evidence_result),
        bounding_boxes=_safe_bounding_boxes(claim.get("bounding_boxes") or claim.get("bounding_box")),
    )


def _missing_required_findings(
    required_claim_ids: set[str],
    findings: list[ClaimFinding],
) -> list[ClaimFinding]:
    present = {
        key
        for finding in findings
        for key in (finding.claim_id, finding.credential_id, finding.field_id)
        if key
    }
    missing_ids = sorted(required_claim_ids - present)
    return [_missing_required_finding(claim_id) for claim_id in missing_ids]


def _missing_required_finding(claim_id: str) -> ClaimFinding:
    safe_id = _safe_identifier(claim_id) or "required-claim"
    return ClaimFinding(
        finding_id=f"finding-{safe_id}",
        claim_id=safe_id,
        credential_id=safe_id,
        field_id=safe_id,
        label=safe_id.replace("_", " ").replace("-", " ").title(),
        claim_type="generic_claim",
        status="AMBER",
        confidence=ClaimFindingConfidence(ai=0.0, verifier=0.0, final=0.0),
        reason_codes=["REQUIRED_CLAIM_MISSING", "MANUAL_REVIEW_REQUIRED"],
        explanation="This required claim is missing verifier-ready evidence and requires manual review.",
        manual_review_required=True,
    )


def _status_and_reasons(
    claim: dict[str, Any],
    result: dict[str, Any] | None,
) -> tuple[ClaimFindingStatus, list[str]]:
    if _is_required_claim_missing(claim):
        return "AMBER", ["REQUIRED_CLAIM_MISSING", "MANUAL_REVIEW_REQUIRED"]

    if result is None:
        reasons = ["NO_VERIFIER_EVIDENCE", "AI_ONLY_EVIDENCE", "LOW_CONFIDENCE_REVIEW_REQUIRED"]
        return "AMBER", reasons

    audit_status = str(result.get("audit_status") or "").upper()
    outcome_color = str(result.get("outcome_color") or "").upper()
    task_status = str(result.get("task_status") or "").upper()
    verifier_status = str(result.get("status") or "").upper()
    result_reasons = [
        str(code).strip().upper()
        for code in list(result.get("reason_codes") or [])
        if str(code).strip()
    ]

    if audit_status == "MISMATCH" or outcome_color == "RED" or verifier_status in {"MISMATCH", "MISMATCHED"}:
        return "RED", ["VERIFIER_MISMATCH"]
    if (
        (audit_status == "VERIFIED" or verifier_status in {"VERIFIED", "MATCHED"})
        and (outcome_color in {"", "GREEN"} or verifier_status in {"VERIFIED", "MATCHED"})
        and _has_verifier_evidence(result)
    ):
        return "GREEN", ["VERIFIER_EVIDENCE_MATCHED"]
    if audit_status == "MANUAL_REVIEW" or task_status == "MANUAL_REVIEW":
        return "AMBER", ["MANUAL_REVIEW_REQUIRED"]
    if task_status == "SKIPPED" or audit_status == "NOT_APPLICABLE" or verifier_status in {"SKIPPED", "NOT_APPLICABLE"}:
        return "AMBER", ["NO_EXECUTABLE_PROVIDER"]
    if task_status in {"FAILED", "ERROR", "TIMEOUT"} or verifier_status in {"ERROR", "TIMEOUT", "UNAVAILABLE"}:
        if any(
            code in {
                "NO_PROVIDER_AVAILABLE",
                "NO_EXECUTABLE_PROVIDER",
                "MANUAL_REVIEW_REQUIRED",
                "MANUAL_REVIEW_PROVIDER_SELECTED",
                "PROVIDER_NOT_REGISTERED",
                "VERIFIER_NOT_REGISTERED",
            }
            for code in result_reasons
        ):
            return "AMBER", result_reasons or ["MANUAL_REVIEW_REQUIRED"]
        return "AMBER", ["PROVIDER_UNAVAILABLE"]
    return "AMBER", ["NO_VERIFIER_EVIDENCE"]


def _is_required_claim_missing(claim: dict[str, Any]) -> bool:
    return (
        bool(claim.get("requires_verification", True))
        and claim.get("has_extracted_value") is False
    )


def _build_result(
    *,
    findings: list[ClaimFinding],
    required_claim_ids: set[str],
) -> TrustFindingsResult:
    counts = TrustFindingCounts(
        green=sum(1 for finding in findings if finding.status == "GREEN"),
        amber=sum(1 for finding in findings if finding.status == "AMBER"),
        red=sum(1 for finding in findings if finding.status == "RED"),
    )
    verifier_backed_evidence = any(
        finding.status == "GREEN" and bool(finding.verifier_refs)
        for finding in findings
    )
    required_findings = [
        finding
        for finding in findings
        if finding.claim_id in required_claim_ids or finding.credential_id in required_claim_ids
    ]

    if counts.red:
        outcome: ClaimFindingStatus = "RED"
        explanation = "At least one required claim has verifier-backed contradictory evidence."
        risk_level = "HIGH"
    elif counts.amber:
        outcome = "AMBER"
        explanation = "At least one claim requires manual review or lacks executable verifier evidence."
        risk_level = "MEDIUM"
    elif required_findings and all(finding.status == "GREEN" for finding in required_findings) and verifier_backed_evidence:
        outcome = "GREEN"
        explanation = "All required claims have verifier-backed matching evidence."
        risk_level = "LOW"
    else:
        outcome = "AMBER"
        explanation = "Required claims do not yet have verifier-backed evidence."
        risk_level = "MEDIUM"

    reason_codes = _dedupe(
        code
        for finding in findings
        for code in finding.reason_codes
    )
    if outcome == "GREEN":
        reason_codes = _dedupe([*reason_codes, "ALL_REQUIRED_CHECKS_MATCHED"])
    elif outcome == "AMBER" and not reason_codes:
        reason_codes = ["NO_VERIFIER_EVIDENCE"]

    final_verdict = FinalVerdict(
        outcome=outcome,
        reason_codes=reason_codes,
        connector_ids=_dedupe(
            finding.source_provider_id
            for finding in findings
            if finding.source_provider_id
        ),
        explanation=explanation,
        risk_level=risk_level,
    )
    return TrustFindingsResult(
        overall_outcome=outcome,
        final_verdict=final_verdict,
        claim_findings=findings,
        finding_counts=counts,
        reason_codes=reason_codes,
        verifier_backed_evidence=verifier_backed_evidence,
    )


def _index_results_by_claim(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        for key_name in ("credential_id", "claim_id", "field_id"):
            key = _safe_string(result.get(key_name))
            if key:
                indexed.setdefault(key, []).append(result)
    return indexed


def _best_result_for_claim(
    claim: dict[str, Any],
    results_by_claim: dict[str, list[dict[str, Any]]],
    all_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for key in {claim.get("credential_id"), claim.get("claim_id"), claim.get("field_id")}:
        safe_key = _safe_string(key)
        if safe_key:
            candidates.extend(results_by_claim.get(safe_key, []))
    if not candidates:
        candidates = list(all_results)
    if not candidates:
        return None
    return max(candidates, key=_result_priority)


def _result_priority(result: dict[str, Any]) -> tuple[int, float]:
    audit_status = str(result.get("audit_status") or "").upper()
    outcome_color = str(result.get("outcome_color") or "").upper()
    if audit_status == "MISMATCH" or outcome_color == "RED":
        return (4, _clamp(result.get("confidence")))
    if audit_status == "VERIFIED" and outcome_color == "GREEN":
        return (3, _clamp(result.get("confidence")))
    if audit_status in {"PARTIAL", "UNVERIFIED"}:
        return (2, _clamp(result.get("confidence")))
    return (1, _clamp(result.get("confidence")))


def _claim_key(claim: dict[str, Any]) -> str:
    return _safe_string(claim.get("credential_id") or claim.get("claim_id") or claim.get("field_id")) or ""


def _has_verifier_evidence(result: dict[str, Any]) -> bool:
    return bool(
        result.get("task_id")
        and (
            result.get("executed_provider_key")
            or result.get("planned_provider_key")
            or result.get("preferred_provider_key")
            or result.get("verifier_key")
            or result.get("connector_id")
            or result.get("provider_id")
        )
    )


def _requires_manual_review(
    status: ClaimFindingStatus,
    reason_codes: list[str],
    result: dict[str, Any] | None,
) -> bool:
    if status != "AMBER":
        return False
    if result and bool(result.get("manual_review_recommended")):
        return True
    return any(code in MANUAL_REVIEW_REASON_CODES for code in reason_codes)


def _safe_explanation(status: ClaimFindingStatus, result: dict[str, Any] | None) -> str:
    if status == "GREEN":
        return "Verifier evidence matched this claim."
    if status == "RED":
        return "Verifier evidence contradicted this claim."
    if result is None:
        return "This claim lacks verifier evidence and requires manual review."
    return "This claim requires manual review because verifier evidence is missing or unavailable."


def _safe_bounding_boxes(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw_boxes = value if isinstance(value, list) else [value]
    safe_boxes = []
    for box in raw_boxes:
        payload = _as_dict(box)
        safe_box = {
            key: payload.get(key)
            for key in ("page", "x", "y", "width", "height", "x0", "y0", "x1", "y1")
            if payload.get(key) is not None
        }
        if safe_box:
            safe_boxes.append(safe_box)
    return safe_boxes


def _safe_reason_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        normalized
        for item in value
        for normalized in [_normalize_reason_code(item)]
        if normalized
    ]


def _normalize_reason_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    upper_text = text.upper()
    if any(marker in upper_text for marker in ("RAW_", "SECRET", "PRIVATE", "GEMINI", "PROVIDER_BODY")):
        return None
    candidate = re.sub(r"[^A-Z0-9]+", "_", upper_text).strip("_")
    if not candidate:
        return None
    candidate = REASON_CODE_ALIASES.get(candidate, candidate)
    if not REASON_CODE_RE.match(candidate):
        return None
    return candidate


def _safe_identifier(value: Any) -> str | None:
    text = _safe_string(value)
    if not text:
        return None
    if any(marker in text.upper() for marker in ("RAW_", "SECRET", "PRIVATE", "GEMINI", "PROVIDER_BODY")):
        return None
    return re.sub(r"[^A-Za-z0-9_.:-]+", "-", text).strip("-") or None


def _safe_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_present(source: dict[str, Any] | None, *keys: str) -> Any:
    if not source:
        return None
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _dedupe(values) -> list[str]:
    return [str(value) for value in dict.fromkeys(value for value in values if value)]
