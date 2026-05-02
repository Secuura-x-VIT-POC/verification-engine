# Secuura x VIT Verification Engine - Phase 1 Shared Contracts

## 1. Purpose

This file freezes the Phase 1 shared JSON/API contracts that Persons A, B, C, D, and E must follow before heavy coding starts.

These contracts define the stable handoff shape between API routes, workflow orchestration, extraction, frontend rendering, trust evaluation, audit reporting, and cleanup. They are intentionally practical: each implementation area should map its work to these shapes before adding deeper backend, frontend, or model logic.

## 2. Non-negotiable rules

- Build generalized platform behavior first. The system must support any PDF document, not only VIT, recruitment, or academic documents.
- AI assists document understanding, extraction normalization, grouping, verifier route recommendation, and explanations.
- AI does not decide final trust.
- The deterministic trust engine owns official green/amber/red system findings.
- GREEN requires verifier-backed evidence. AI-only confidence, even high confidence, must never produce GREEN.
- AMBER covers missing evidence, no provider, no executable provider, provider unavailable, provider capability mismatch, manual-review fallback, AI-only evidence, low confidence, and missing required claims.
- RED covers provider mismatch, hard invalid verifier results, hard contradictions, unsafe documents, and malformed decisive failures.
- Overall document outcome follows RED > AMBER > GREEN. Any RED claim makes the document RED; otherwise any AMBER claim makes it AMBER; GREEN is allowed only when all required claims are GREEN with verifier-backed evidence.
- A human reviewer owns the final approve/reject/manual-review decision.
- Persistent audit artifacts must not contain PII, raw document content, raw OCR output, full Gemini prompts/responses, or raw verifier evidence.
- The frontend receives only a sanitized workspace payload.

## 3. Ownership

Owners: Person A + Person B + Person D

Reviewers: Person C + Person E

How each person uses this contract:

- Person A: API routes, session lifecycle, and review-decision handling must use these request/response contracts.
- Person B: workflow state, trust engine inputs/outputs, and LangGraph integration must preserve these shapes.
- Person C: extraction output must map into `CredentialFinding` inputs.
- Person D: frontend must render only `WorkspacePayload`.
- Person E: audit, privacy, retention, and cleanup must use `AuditSummary`.

## 4. SessionState contract

Allowed states are exactly:

```text
CREATED
UPLOAD_PENDING
UPLOADED_PENDING_REVIEW
VERIFYING
VERIFIED_GREEN
VERIFIED_AMBER
VERIFIED_RED
PENDING_HUMAN_REVIEW
HUMAN_APPROVED
HUMAN_REJECTED
MANUAL_REVIEW_REQUIRED
PENDING_CLEANUP
PURGE_COMPLETE
FAILED_RETRIABLE
FAILED_PURGED
ABANDONED_VERIFYING
```

`VERIFIED_GREEN`, `VERIFIED_AMBER`, and `VERIFIED_RED` are legacy/backward-compatible system finding states. They may remain in code and tests while older sessions are supported, but new normal completed runs should prefer `PENDING_HUMAN_REVIEW` with the color result stored separately.

`PENDING_HUMAN_REVIEW` is mandatory before final approval, rejection, or manual-review classification.

GREEN, AMBER, and RED must be represented as `trust_outcome`, `overall_outcome`, or `final_verdict.outcome`, not as final workflow approval states. Frontend code should read `status` for workflow state and `overall_outcome`/`final_verdict.outcome` for the color result.

Final human states must lead to cleanup.

Normal transition:

```text
CREATED
-> UPLOAD_PENDING
-> UPLOADED_PENDING_REVIEW
-> VERIFYING
-> PENDING_HUMAN_REVIEW
-> HUMAN_APPROVED/HUMAN_REJECTED/MANUAL_REVIEW_REQUIRED
-> PENDING_CLEANUP
-> PURGE_COMPLETE
```

Failure/retry transitions:

```text
VERIFYING -> FAILED_RETRIABLE
VERIFYING -> ABANDONED_VERIFYING
FAILED_RETRIABLE -> VERIFYING
PENDING_CLEANUP -> FAILED_PURGED/PURGE_COMPLETE
```

## 5. CredentialFinding contract

`CredentialFinding` is the frontend-visible field/claim finding generated from extraction, verifier outputs, and deterministic trust rules.

```json
{
  "finding_id": "finding_01HZX4A9R7QK",
  "claim_id": "credential_01HZX49Y8D2M",
  "credential_id": "credential_01HZX49Y8D2M",
  "field_id": "field_issuer_name",
  "field_label": "Issuer name",
  "display_value": "Example Institution",
  "masked_value": "Example I**********",
  "claim_type": "ISSUER_IDENTITY",
  "status": "GREEN",
  "confidence": {
    "extraction": 0.94,
    "ai": 0.88,
    "grounding": 0.91,
    "verifier": 0.97,
    "final": 0.93
  },
  "reason_codes": [
    "ISSUER_MATCHED",
    "DOCUMENT_STRUCTURE_SUPPORTED"
  ],
  "explanation": "Issuer identity matched the selected verifier route and no policy conflict was found.",
  "page_number": 1,
  "bounding_boxes": [
    {
      "page": 1,
      "x": 0.12,
      "y": 0.18,
      "width": 0.42,
      "height": 0.04
    }
  ],
  "verifier_refs": [
    "task_result_01HZX4C1T8ZM"
  ],
  "manual_review_required": false,
  "requires_human_attention": false
}
```

Allowed `status` values:

```text
GREEN
AMBER
RED
```

Canonical Phase 6 finding rules:

- GREEN means verifier-backed evidence matched the claim. `verifier_refs` or safe provider/verifier identifiers must be present.
- AMBER means the claim needs human review because evidence is missing, unavailable, AI-only, low confidence, no executable provider exists, provider capability does not match, the provider returned manual review, or the required claim is missing.
- RED means verifier evidence found a mismatch, hard invalid result, or hard contradiction.
- `reason_codes` must be deterministic machine-style codes such as `VERIFIED_BY_PROVIDER`, `NO_VERIFIER_EVIDENCE`, `AI_ONLY_EVIDENCE`, `REQUIRED_CLAIM_MISSING`, or `PROVIDER_MISMATCH`. Duplicate reason codes must be removed.
- `manual_review_required` must be true for AMBER findings and false for GREEN provider-backed findings. RED findings may still be shown to the reviewer through the normal human review workflow.

Privacy note: `display_value` and `masked_value` may be shown only in the active workspace. Final persisted/audit-safe findings must not include raw OCR text, raw PDF text, raw credential values, raw normalized values, full document text, raw Gemini output, raw provider bodies, or reviewer-note plaintext.

## 6. VerificationTask contract

`VerificationTask` is planner output before verifier execution. It describes what should be checked, which verifier routes are candidates, and the assurance level required.

```json
{
  "task_id": "task_01HZX4B5A0KR",
  "credential_id": "credential_01HZX49Y8D2M",
  "claim_type": "ISSUER_IDENTITY",
  "field_ids": [
    "field_issuer_name",
    "field_document_type"
  ],
  "provider_candidates": [
    {
      "provider_id": "provider_registry_example",
      "provider_label": "Example Registry",
      "provider_mode": "live"
    },
    {
      "provider_id": "provider_fixture_example",
      "provider_label": "Example Fixture",
      "provider_mode": "local_fixture"
    }
  ],
  "required_fields": [
    "issuer_name",
    "document_type"
  ],
  "assurance_required": "HIGH",
  "priority": "REQUIRED",
  "input_payload": {
    "issuer_name": "Example Institution",
    "document_type": "Certificate"
  },
  "planner_reason": "Issuer and document type require authoritative route validation."
}
```

Allowed `assurance_required` values:

```text
LOW
MEDIUM
HIGH
```

Allowed `priority` values:

```text
REQUIRED
OPTIONAL
```

`input_payload` may contain active-session values needed by verifiers, but it must not be stored in the final audit.

Compatibility note: Phase 1 may accept `provider_candidates` in either simple form, such as `["entra_verified_id", "local_mock_registry"]`, or expanded form, such as `[{"provider_id": "entra_verified_id", "provider_label": "Microsoft Entra Verified ID", "provider_mode": "live"}]`. The expanded object form is preferred for frontend rendering and debugging because it carries labels and execution mode explicitly.

## 7. VerificationTaskResult contract

`VerificationTaskResult` is the normalized verifier result. It converts mock, live, local fixture, disabled, unavailable, timeout, and error outcomes into one stable shape for the trust engine.

```json
{
  "task_id": "task_01HZX4B5A0KR",
  "credential_id": "credential_01HZX49Y8D2M",
  "claim_type": "ISSUER_IDENTITY",
  "provider_id": "provider_registry_example",
  "provider_label": "Example Registry",
  "provider_mode": "live",
  "status": "MATCHED",
  "confidence": 0.97,
  "reason_codes": [
    "REGISTRY_MATCHED",
    "FIELDS_CONFIRMED"
  ],
  "evidence_summary": "Verifier confirmed issuer identity and document category.",
  "checked_fields": [
    "issuer_name",
    "document_type"
  ],
  "matched_fields": [
    "issuer_name",
    "document_type"
  ],
  "mismatched_fields": [],
  "missing_fields": [],
  "latency_ms": 842,
  "executed_at": "2026-04-29T10:30:00Z",
  "raw_response_retention_policy": "DO_NOT_STORE"
}
```

Allowed `provider_mode` values:

```text
mock
live
local_fixture
disabled
```

Allowed `status` values:

```text
MATCHED
MISMATCHED
PARTIAL
UNAVAILABLE
TIMEOUT
ERROR
SKIPPED
NOT_APPLICABLE
```

Mock providers must be honestly labelled as `mock`. Never store the raw provider response body.

## 8. AuditSummary contract

`AuditSummary` is the final durable non-PII audit/report shape. It is the artifact allowed to remain after sensitive session data is cleaned up.

```json
{
  "audit_receipt_id": "audit_01HZX4F4MP9V",
  "session_id": "session_01HZX48MY9DW",
  "document_commitment": "sha256:8f4f6f4d5f3a5b0f9e1c2d3a4b5c6d7e8f90123456789abcdef0123456789abc",
  "document_type": "Certificate",
  "overall_outcome": "GREEN",
  "reviewer_decision": "APPROVED",
  "finding_counts": {
    "green": 8,
    "amber": 0,
    "red": 0
  },
  "reason_codes": [
    "ALL_REQUIRED_CHECKS_MATCHED",
    "HUMAN_REVIEW_APPROVED"
  ],
  "connector_ids": [
    "provider_registry_example"
  ],
  "issued_at": "2026-04-29T10:35:00Z",
  "approved_at": "2026-04-29T10:40:00Z",
  "rejected_at": null,
  "manual_review_at": null,
  "reviewer_note_hash": "sha256:4a44dc15364204a80fe80e9039455cc1f5ad6a1a9b0f9c7f0f1b2c3d4e5f6078",
  "receipt_hash": "sha256:2f1d8e9c0b7a6543210fedcba9876543210fedcba9876543210fedcba9876543",
  "signature": "sec-signature-placeholder",
  "hash_chain_prev": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "cleanup_status": "PURGE_COMPLETE"
}
```

Allowed `overall_outcome` values:

```text
GREEN
AMBER
RED
```

Allowed `reviewer_decision` values:

```text
APPROVED
REJECTED
MANUAL_REVIEW_REQUIRED
```

Must not contain:

- Raw name
- Raw ID number
- Raw marks
- Raw address
- Raw OCR text
- Raw PDF text
- Full Gemini output
- Full verifier response body
- Unredacted reviewer note

## 9. ReviewDecisionRequest contract

Request JSON:

```json
{
  "decision": "APPROVE",
  "reviewer_note": "Document accepted after reviewing green/amber/red findings."
}
```

Allowed `decision` values:

```text
APPROVE
REJECT
NEEDS_MANUAL_REVIEW
```

Backend mapping:

```text
APPROVE -> HUMAN_APPROVED -> APPROVED
REJECT -> HUMAN_REJECTED -> REJECTED
NEEDS_MANUAL_REVIEW -> MANUAL_REVIEW_REQUIRED -> MANUAL_REVIEW_REQUIRED
```

Validation:

- `NEEDS_MANUAL_REVIEW` requires `reviewer_note`.
- `reviewer_note` must never be stored raw.
- Only `reviewer_note_hash` may be persisted.

## 10. WorkspacePayload contract

`WorkspacePayload` is the single frontend contract. The frontend must render from this sanitized payload instead of depending on backend internals, raw extraction output, verifier internals, or model responses.

Workspace payloads must not include raw OCR text, raw PDF text, full Gemini output, raw verifier response bodies, or unredacted reviewer notes.

After verification completes, `WorkspacePayload.status` remains `PENDING_HUMAN_REVIEW`. The color outcome is exposed separately through `final_verdict.outcome` and summary counts, not by moving directly to a final approval/rejection workflow state.

```json
{
  "session_id": "session_01HZX48MY9DW",
  "status": "PENDING_HUMAN_REVIEW",
  "ui_status": "Ready for human review",
  "document": {
    "document_id": "document_01HZX48Z0A9C",
    "document_type": "Certificate",
    "page_count": 2,
    "uploaded_at": "2026-04-29T10:20:00Z",
    "content_retention_policy": "PURGE_AFTER_REVIEW"
  },
  "summary": {
    "overall_outcome": "GREEN",
    "finding_counts": {
      "green": 8,
      "amber": 0,
      "red": 0
    },
    "requires_human_attention": false,
    "reason_codes": [
      "ALL_REQUIRED_CHECKS_MATCHED"
    ]
  },
  "findings": [
    {
      "finding_id": "finding_01HZX4A9R7QK",
      "credential_id": "credential_01HZX49Y8D2M",
      "field_id": "field_issuer_name",
      "field_label": "Issuer name",
      "display_value": "Example Institution",
      "masked_value": "Example I**********",
      "claim_type": "ISSUER_IDENTITY",
      "status": "GREEN",
      "confidence": {
        "extraction": 0.94,
        "ai": 0.88,
        "grounding": 0.91,
        "verifier": 0.97,
        "final": 0.93
      },
      "reason_codes": [
        "ISSUER_MATCHED"
      ],
      "explanation": "Issuer identity matched the selected verifier route.",
      "page_number": 1,
      "bounding_boxes": [],
      "verifier_refs": [
        "task_result_01HZX4C1T8ZM"
      ],
      "requires_human_attention": false
    }
  ],
  "verification_tasks": [
    {
      "task_id": "task_01HZX4B5A0KR",
      "credential_id": "credential_01HZX49Y8D2M",
      "claim_type": "ISSUER_IDENTITY",
      "field_ids": [
        "field_issuer_name"
      ],
      "provider_candidates": [
        {
          "provider_id": "provider_registry_example",
          "provider_label": "Example Registry",
          "provider_mode": "live"
        }
      ],
      "required_fields": [
        "issuer_name"
      ],
      "assurance_required": "HIGH",
      "priority": "REQUIRED",
      "input_payload": {
        "issuer_name": "Example Institution"
      },
      "planner_reason": "Issuer identity requires registry validation."
    }
  ],
  "task_results": [
    {
      "task_id": "task_01HZX4B5A0KR",
      "credential_id": "credential_01HZX49Y8D2M",
      "claim_type": "ISSUER_IDENTITY",
      "provider_id": "provider_registry_example",
      "provider_label": "Example Registry",
      "provider_mode": "live",
      "status": "MATCHED",
      "confidence": 0.97,
      "reason_codes": [
        "REGISTRY_MATCHED"
      ],
      "evidence_summary": "Verifier confirmed issuer identity.",
      "checked_fields": [
        "issuer_name"
      ],
      "matched_fields": [
        "issuer_name"
      ],
      "mismatched_fields": [],
      "missing_fields": [],
      "latency_ms": 842,
      "executed_at": "2026-04-29T10:30:00Z",
      "raw_response_retention_policy": "DO_NOT_STORE"
    }
  ],
  "audit_summary": null,
  "actions": {
    "can_rerun": true,
    "can_manual_override": true,
    "can_export_report": false,
    "can_close": true,
    "can_submit_review_decision": true
  }
}
```

Endpoint rules:

- `POST /api/v1/verification-sessions/{session_id}/run` starts or reruns verification.
- `GET /api/v1/verification-sessions/{session_id}/workspace` reads the latest sanitized workspace.
- `GET /workspace` must not rerun Gemini or verifiers every time.

## 11. Endpoint contract summary

### `POST /api/v1/verification-sessions/{session_id}/run`

Starts or reruns verification for an uploaded document session.

Input: path `session_id`; optional run controls if required by implementation.

Output: `WorkspacePayload` or a status response compatible with `WorkspacePayload`.

### `GET /api/v1/verification-sessions/{session_id}/workspace`

Reads the latest sanitized workspace for frontend rendering.

Input: path `session_id`.

Output: `WorkspacePayload`.

### `POST /api/v1/verification-sessions/{session_id}/review-decision`

Submits the human review decision after green/amber/red findings are available.

Input: path `session_id`; body `ReviewDecisionRequest`.

Output: updated `WorkspacePayload` or updated session/review status compatible with `WorkspacePayload`.

### `POST /sessions/{session_id}/close`

Closes the session and starts or confirms cleanup of sensitive active-session data.

Input: path `session_id`.

Output: cleanup status and, when available, sanitized `AuditSummary`.

## 12. Acceptance checklist

- [ ] All members agree on SessionState list.
- [ ] Frontend uses only WorkspacePayload.
- [ ] Backend run endpoint returns WorkspacePayload or status compatible with it.
- [ ] Review decision endpoint uses ReviewDecisionRequest.
- [ ] Audit persists only AuditSummary-safe fields.
- [ ] No raw OCR/PDF/Gemini/verifier evidence in persisted audit.
- [ ] Mock verifier mode is clearly labelled.
- [ ] Green/amber/red are system findings, not final human approval.
- [ ] Human review exists before cleanup.
- [ ] Person C extraction output can map to CredentialFinding.
- [ ] Person E cleanup leaves only audit receipt/report.
