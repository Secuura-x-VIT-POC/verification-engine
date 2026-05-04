from __future__ import annotations

from unittest.mock import patch

from extraction.evidence_graph import build_evidence_graph_from_pp_chatocr

from backend.app.agent_orchestration.graph import _build_workspace_payload, _gemini_dynamic_schema_discovery
from backend.app.agent_orchestration.policies import AgentRuntimePolicy
from backend.app.agent_orchestration.sanitization import sanitize_workspace_payload
from backend.app.agent_orchestration.schemas import DynamicDocumentSchema
from backend.app.verification_domain.planner import build_planned_credentials


class _MockStructuredLlm:
    def invoke(self, _prompt):
        return DynamicDocumentSchema(
            document_type="arbitrary_lab_report",
            document_subtype=None,
            issuing_entity="North Clinic",
            document_purpose="record verification",
            overall_confidence=0.91,
            claims=[
                {
                    "claim_id": "claim_patient_code",
                    "label": "Patient Code",
                    "value": "PX-991",
                    "normalized_value": "PX-991",
                    "data_type": "identifier",
                    "importance": "critical",
                    "requires_verification": True,
                    "verification_intent": "generic_record",
                    "evidence_ids": ["ev-code"],
                    "page_number": 1,
                    "confidence": 0.88,
                    "reason": "Visible identifier label and value.",
                },
                {
                    "claim_id": "claim_unmatched",
                    "label": "External Reference",
                    "value": "REF-404",
                    "normalized_value": "REF-404",
                    "data_type": "identifier",
                    "importance": "important",
                    "requires_verification": True,
                    "verification_intent": "manual_review",
                    "evidence_ids": ["missing-id"],
                    "page_number": 1,
                    "confidence": 0.7,
                    "reason": "Model cited an invalid evidence id.",
                },
            ],
        )


def _policy() -> AgentRuntimePolicy:
    return AgentRuntimePolicy(
        orchestration_enabled=True,
        provider_key="gemini",
        gemini_api_key="configured",
        gemini_primary_configured=True,
        gemini_structured_output_enabled=True,
    )


def test_pp_evidence_graph_from_mocked_visual_tokens_blocks_tables():
    graph = build_evidence_graph_from_pp_chatocr(
        {
            "page_count": 1,
            "spatial_text_map": [
                {
                    "evidence_id": "ev-code",
                    "text_preview": "Patient Code PX-991",
                    "page_number": 1,
                    "bbox": [10, 20, 160, 40],
                    "confidence": 0.96,
                    "source_width": 800,
                    "source_height": 1000,
                }
            ],
            "layout_blocks": [{"layout_block_id": "lb-1", "text_preview": "North Clinic", "bbox": [8, 8, 120, 18]}],
            "table_cells": [{"table_cell_id": "tc-1", "text_preview": "Glucose 91", "bbox": [20, 60, 140, 80], "row_index": 0, "column_index": 1}],
        }
    )

    assert graph["source"] == "pp_chatocr_v4"
    assert graph["coordinate_space"] == "pp_chatocr_image_pixels"
    assert [item["source_type"] for item in graph["evidence"]] == ["token", "layout_block", "table_cell"]
    assert graph["evidence"][0]["text_preview"] == "Patient Code PX-991"


def test_mocked_gemini_dynamic_schema_preserves_arbitrary_claims_and_pp_geometry():
    evidence_graph = {
        "source": "pp_chatocr_v4",
        "coordinate_space": "pp_chatocr_image_pixels",
        "page_count": 1,
        "evidence": [
            {
                "evidence_id": "ev-code",
                "page_number": 1,
                "text_preview": "Patient Code PX-991",
                "source_type": "line",
                "bbox": [10, 20, 160, 40],
                "polygon": [[10, 20], [160, 20], [160, 40], [10, 40]],
                "confidence": 0.96,
                "reading_order": 1,
                "coordinate_space": "pp_chatocr_image_pixels",
                "source_width": 800,
                "source_height": 1000,
            }
        ],
    }

    with patch("backend.app.agent_orchestration.graph._build_structured_gemini_llm", return_value=_MockStructuredLlm()):
        result = _gemini_dynamic_schema_discovery({"extraction_payload": {"view": {"evidence_graph": evidence_graph}}}, _policy())

    claims = result["dynamic_claims"]
    assert [claim["label"] for claim in claims] == ["Patient Code", "External Reference"]
    assert claims[0]["evidence_ids"] == ["ev-code"]
    assert claims[0]["bbox"] == [10, 20, 160, 40]
    assert claims[0]["coordinate_space"] == "pp_chatocr_image_pixels"
    assert claims[0]["source_width"] == 800
    assert claims[1]["grounding_status"] == "unresolved"
    assert "GROUNDING_UNRESOLVED" in claims[1]["reason_codes"]


def test_schema_failure_and_zero_claims_return_manual_review_warnings():
    evidence_graph = {
        "source": "pp_chatocr_v4",
        "evidence": [{"evidence_id": "ev-1", "text_preview": "Only visible text", "page_number": 1, "source_type": "line"}],
    }

    failed = _gemini_dynamic_schema_discovery({"extraction_payload": {"view": {"evidence_graph": evidence_graph}}}, AgentRuntimePolicy())
    assert "SCHEMA_INFERENCE_FAILED" in failed["dynamic_schema"]["warnings"]
    assert failed["dynamic_claims"] == []

    class EmptyLlm:
        def invoke(self, _prompt):
            return DynamicDocumentSchema(document_type="unknown", claims=[])

    with patch("backend.app.agent_orchestration.graph._build_structured_gemini_llm", return_value=EmptyLlm()):
        empty = _gemini_dynamic_schema_discovery({"extraction_payload": {"view": {"evidence_graph": evidence_graph}}}, _policy())
    assert "NO_DYNAMIC_CLAIMS_EXTRACTED" in empty["dynamic_schema"]["warnings"]


def test_schema_failure_preserves_deterministic_label_value_fields():
    evidence_graph = {
        "source": "pp_chatocr_v4",
        "evidence": [{"evidence_id": "ev-app", "text_preview": "Application ID : EN24235978", "page_number": 1, "source_type": "line"}],
    }
    extraction_payload = {
        "view": {
            "evidence_graph": evidence_graph,
            "field_details": [
                {
                    "field_id": "application_id_abc123",
                    "key": "application_id",
                    "label": "Application ID",
                    "value": "EN24235978",
                    "extracted_value": "EN24235978",
                    "masked_value": "****5978",
                    "confidence": 0.92,
                    "bbox": [132, 20, 230, 35],
                    "page_number": 1,
                    "coordinate_space": "pp_chatocr_image_pixels",
                    "source_width": 1000,
                    "source_height": 1400,
                    "evidence_ref": "ev-app",
                }
            ],
        }
    }

    failed = _gemini_dynamic_schema_discovery({"extraction_payload": extraction_payload}, AgentRuntimePolicy())

    assert "SCHEMA_INFERENCE_FAILED" in failed["dynamic_schema"]["warnings"]
    assert [claim["label"] for claim in failed["dynamic_claims"]] == ["Application ID"]
    assert failed["dynamic_claims"][0]["value"] == "EN24235978"
    assert failed["dynamic_claims"][0]["source_width"] == 1000
    assert not failed["dynamic_claims"][0]["label"].startswith("Visible Text")


def test_workspace_boxes_keep_source_dimensions_after_tightening():
    extraction_payload = {
        "view": {
            "document_type": "generic_document",
            "page_count": 1,
            "used_ocr": True,
            "warnings": [],
            "dynamic_claims": [
                {
                    "claim_id": "application_id",
                    "field_id": "application_id",
                    "label": "Application ID",
                    "value": "EN24235978",
                    "evidence_ids": ["ev-value"],
                }
            ],
            "evidence_graph": {
                "evidence": [
                    {
                        "evidence_id": "ev-value",
                        "page_number": 1,
                        "text_preview": "EN24235978",
                        "bbox": [132, 20, 230, 35],
                        "coordinate_space": "pp_chatocr_image_pixels",
                        "source_width": 1000,
                        "source_height": 1400,
                        "source": "pp_chatocr_v4",
                    }
                ]
            },
        }
    }

    result = _build_workspace_payload(
        {
            "session_id": "session-source-dimensions",
            "filename": "document.pdf",
            "sanitized_extraction": extraction_payload,
            "document_understanding": {"document_type": "generic_document"},
            "field_decisions": [
                {
                    "field_id": "application_id",
                    "label": "Application ID",
                    "extracted_value": "EN24235978",
                    "normalized_value": "EN24235978",
                    "status": "AMBER",
                    "reason_codes": ["MANUAL_REVIEW_REQUIRED"],
                    "bounding_boxes": [],
                }
            ],
            "verifier_results": [],
            "final_verdict": {"outcome": "AMBER", "reason_codes": ["MANUAL_REVIEW_REQUIRED"]},
            "audit_log": [],
        }
    )

    box = result["workspace_payload"]["fields"][0]["bounding_boxes"][0]
    assert box["coordinate_space"] == "pp_chatocr_image_pixels"
    assert box["source_width"] == 1000
    assert box["source_height"] == 1400


def test_dynamic_planner_routes_by_intent_and_data_type_not_label():
    extraction_payload = {
        "view": {
            "document_type": "unknown",
            "dynamic_claims": [
                {
                    "claim_id": "weird-1",
                    "field_id": "weird-1",
                    "label": "Completely Novel Label",
                    "value": "ZX-100",
                    "normalized_value": "ZX-100",
                    "data_type": "identifier",
                    "verification_intent": "academic",
                    "importance": "critical",
                    "confidence": 0.9,
                    "bounding_box": {"page": 1, "x0": 1, "y0": 2, "x1": 3, "y1": 4},
                }
            ],
        }
    }
    credentials, context = build_planned_credentials(extraction_payload)
    assert not context
    assert credentials[0].category == "academic"
    assert credentials[0].requires_verification is True


def test_workspace_sanitizer_drops_raw_gemini_pp_and_verifier_payloads_but_keeps_geometry():
    payload = sanitize_workspace_payload(
        {
            "raw_pp_chatocr_output": "secret",
            "raw_gemini_prompt": "secret",
            "raw_gemini_response": "secret",
            "verifier_request_body": {"secret": True},
            "fields": [
                {
                    "label": "Arbitrary",
                    "masked_value": "PX***91",
                    "evidence_ids": ["ev-code"],
                    "bbox": [10, 20, 160, 40],
                    "coordinate_space": "pp_chatocr_image_pixels",
                }
            ],
        }
    )
    assert "raw_pp_chatocr_output" not in payload
    assert "raw_gemini_prompt" not in payload
    assert "verifier_request_body" not in payload
    assert payload["fields"][0]["bbox"] == [10, 20, 160, 40]
