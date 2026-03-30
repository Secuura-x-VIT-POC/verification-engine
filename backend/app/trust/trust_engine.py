def evaluate_trust(policy: dict, extraction_data: dict, connector_responses: list) -> dict:
    """
    policy: comes from session (NOT user input)
        {
            "requires_high_assurance": True/False,
            "required_connectors": ["vit_registry"],
        }
    """

    reason_codes = []
    used_connector_ids = [c.get("connector_id") for c in connector_responses]

    # -----------------------------
    # 0. Hard sanity check
    # -----------------------------
    if not extraction_data:
        return format_result("RED", ["NO_EXTRACTION_DATA"], used_connector_ids)

    # -----------------------------
    # 1. Fatal Document Flaws
    # -----------------------------
    if extraction_data.get("is_unsafe") or extraction_data.get("critical_tamper_signal"):
        return format_result("RED", ["UNSAFE_OR_TAMPERED"], used_connector_ids)

    # -----------------------------
    # 2. Grounding Failures
    # -----------------------------
    missing_mandatory = [
        f["name"] for f in extraction_data.get("fields", [])
        if f.get("is_mandatory") and not f.get("is_grounded")
    ]
    if missing_mandatory:
        return format_result("RED", ["INSUFFICIENT_GROUNDING"], used_connector_ids)

    # -----------------------------
    # 3. Connector Contradictions
    # -----------------------------
    for conn in connector_responses:
        if conn.get("status") in ["REVOKED", "INVALID"]:
            return format_result("RED", ["CREDENTIAL_REVOKED"], used_connector_ids)

        if conn.get("mismatched_claims"):
            return format_result("RED", ["CRITICAL_MISMATCH"], used_connector_ids)

    # -----------------------------
    # 4. Connector Availability / Timeout Policy
    # -----------------------------
    required_connectors = policy.get("required_connectors", [])
    requires_high_assurance = policy.get("requires_high_assurance", False)

    connector_map = {c["connector_id"]: c for c in connector_responses}

    # Check required connectors
    for rc in required_connectors:
        conn = connector_map.get(rc)

        # No response at all
        if not conn:
            if requires_high_assurance:
                return format_result("RED", ["REQUIRED_CONNECTOR_MISSING"], used_connector_ids)
            else:
                reason_codes.append("OPTIONAL_CONNECTOR_MISSING")
                continue

        # Timeout after retries
        if conn.get("status") == "TIMEOUT_AFTER_RETRIES":
            if requires_high_assurance or conn.get("assurance_class") == "HIGH":
                return format_result("RED", ["REQUIRED_CONNECTOR_UNAVAILABLE"], used_connector_ids)
            else:
                reason_codes.append("OPTIONAL_CONNECTOR_TIMEOUT")

    # -----------------------------
    # 5. GREEN (strict)
    # -----------------------------
    verified_required = [
        c for c in connector_responses
        if c.get("status") == "VERIFIED"
        and c.get("connector_id") in required_connectors
    ]

    if verified_required:
        return format_result(
            "GREEN",
            ["TRUSTED_SOURCE_VERIFIED", "GROUNDING_OK"],
            used_connector_ids
        )

    # -----------------------------
    # 6. AMBER fallback
    # -----------------------------
    if not requires_high_assurance:
        reason_codes.append("VERIFICATION_OPTIONAL_APPLIED")
        return format_result("AMBER", reason_codes, used_connector_ids)

    # -----------------------------
    # 7. Final strict fallback
    # -----------------------------
    return format_result("RED", ["POLICY_BREACH_NO_VERIFIED_SOURCE"], used_connector_ids)


def format_result(outcome: str, reason_codes: list, connector_ids: list) -> dict:
    print(outcome)

    return {
        "outcome": outcome,
        "reason_codes": list(set(reason_codes)),  # remove duplicates
        "connector_ids": connector_ids
    }