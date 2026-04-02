from __future__ import annotations

import logging
from typing import Any


LOGGER = logging.getLogger(__name__)


def evaluate_trust(extraction_data: dict, connector_result: dict | list[dict] | None, policy: dict) -> dict:
    resolved_policy = _resolve_policy(extraction_data or {}, policy or {})
    normalized_fields = _normalize_extraction_fields(extraction_data or {}, resolved_policy)
    connectors = _normalize_connector_results(connector_result)
    connector_ids = [connector["connector_id"] for connector in connectors if connector.get("connector_id")]

    mismatch = _find_connector(connectors, status="MISMATCH")
    if mismatch is not None:
        return _format_result("RED", ["CONNECTOR_MISMATCH"], connector_ids)

    for field_name in resolved_policy["required_fields"]:
        field_data = normalized_fields.get(field_name)
        if not field_data or not field_data["present"]:
            return _format_result("RED", ["MISSING_REQUIRED_FIELD"], connector_ids)

        if not field_data["has_grounding"]:
            return _format_result("RED", ["GROUNDING_MISSING"], connector_ids)

        if field_data["confidence"] < resolved_policy["min_confidence_threshold"]:
            return _format_result("RED", ["LOW_CONFIDENCE"], connector_ids)

    timeout_required = _find_required_timeout(connectors)
    if timeout_required is not None:
        return _format_result("RED", ["CONNECTOR_TIMEOUT_REQUIRED"], connector_ids)

    verified_connector = _find_connector(connectors, status="VERIFIED")
    if verified_connector is not None:
        return _format_result("GREEN", ["CONNECTOR_VERIFIED"], connector_ids)

    timeout_optional = _find_optional_timeout(connectors)
    if timeout_optional is not None:
        return _format_result("AMBER", ["NOT_VERIFIED"], connector_ids)

    error_connector = _find_connector(connectors, status="ERROR")
    if error_connector is not None:
        return _format_result("AMBER", ["NOT_VERIFIED"], connector_ids)

    if not resolved_policy["require_connector"]:
        return _format_result("AMBER", ["OPTIONAL_VERIFICATION_SKIPPED"], connector_ids)

    return _format_result("AMBER", ["NOT_VERIFIED"], connector_ids)


def _resolve_policy(extraction_data: dict, policy: dict) -> dict[str, Any]:
    required_fields = list(policy.get("required_fields") or [])
    if not required_fields:
        fields = extraction_data.get("fields") or []
        if isinstance(fields, list):
            required_fields = [
                str(field.get("name"))
                for field in fields
                if field.get("is_mandatory") and field.get("name")
            ]

    require_connector = policy.get("require_connector")
    if require_connector is None:
        require_connector = bool(policy.get("required_connectors"))

    return {
        "required_fields": required_fields,
        "min_confidence_threshold": float(policy.get("min_confidence_threshold", 0)),
        "require_connector": bool(require_connector),
    }


def _normalize_extraction_fields(extraction_data: dict, policy: dict) -> dict[str, dict[str, Any]]:
    fields = extraction_data.get("fields") or {}
    confidence_map = extraction_data.get("confidence") or {}
    bounding_boxes = extraction_data.get("bounding_boxes") or {}

    if isinstance(fields, list):
        normalized: dict[str, dict[str, Any]] = {}
        for field in fields:
            name = str(field.get("name"))
            if not name:
                continue
            value = field.get("value")
            normalized[name] = {
                "present": value not in (None, "", []) if "value" in field else True,
                "has_grounding": bool(field.get("is_grounded")),
                "confidence": float(field.get("confidence", policy["min_confidence_threshold"] or 1.0)),
            }
        return normalized

    normalized = {}
    for field_name, value in fields.items():
        normalized[field_name] = {
            "present": value not in (None, "", []),
            "has_grounding": _has_grounding_entry(bounding_boxes.get(field_name)),
            "confidence": float(confidence_map.get(field_name, 0)),
        }
    return normalized


def _normalize_connector_results(connector_result: dict | list[dict] | None) -> list[dict]:
    if connector_result is None:
        return []

    raw_connectors = connector_result if isinstance(connector_result, list) else [connector_result]
    normalized = []
    for connector in raw_connectors:
        normalized.append(
            {
                "connector_id": str(connector.get("connector_id", "")),
                "status": str(connector.get("status", "ERROR")).upper(),
                "reason_codes": list(connector.get("reason_codes") or []),
                "assurance_class": str(connector.get("assurance_class", "HIGH")).upper(),
            }
        )
    return normalized


def _find_connector(connectors: list[dict], *, status: str) -> dict | None:
    for connector in connectors:
        if connector["status"] == status:
            return connector
    return None


def _find_required_timeout(connectors: list[dict]) -> dict | None:
    for connector in connectors:
        if connector["status"] == "TIMEOUT" and connector["assurance_class"] == "HIGH":
            return connector
    return None


def _find_optional_timeout(connectors: list[dict]) -> dict | None:
    for connector in connectors:
        if connector["status"] == "TIMEOUT" and connector["assurance_class"] != "HIGH":
            return connector
    return None


def _has_grounding_entry(entry: Any) -> bool:
    if entry is None:
        return False
    if isinstance(entry, list):
        return len(entry) > 0
    if isinstance(entry, dict):
        return bool(entry)
    return False


def _format_result(outcome: str, reason_codes: list[str], connector_ids: list[str]) -> dict:
    LOGGER.info(
        "TRUST_EVALUATED: outcome=%s, reasons=%s",
        outcome,
        reason_codes,
    )
    return {
        "outcome": outcome,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "connector_ids": connector_ids,
    }
