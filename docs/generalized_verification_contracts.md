# Generalized Verification Contracts

## Purpose

The generalized verification layer turns the existing session-driven verification pipeline into a broader document verification foundation without replacing the current FastAPI wiring, workflow state machine, or deterministic trust engine.

Stage 4 adds a real per-credential verifier execution backbone on top of the Stage 2 and Stage 3 artifacts.

The implementation remains intentionally:

- additive
- deterministic
- session-scoped
- backward compatible with older rows
- modular enough for future LangGraph orchestration
- free of real provider credentials in this stage

## Persisted Session Artifacts

The `verification_sessions` row now stores two additive families of derived artifacts.

### Generalized analysis artifacts

- `document_profile_payload`
- `generalized_credentials_payload`
- `verification_plan_payload`
- `credential_audits_payload`
- `verification_summary_payload`
- `generalized_analysis_status`
- `generalized_analysis_error`

### Verifier execution artifacts

- `verification_task_results_payload`
- `credential_verification_bundles_payload`
- `verification_execution_summary_payload`
- `verification_execution_status`
- `verification_execution_error`

All of these fields are nullable and safe for older rows.

## Core Analysis Contracts

### `DocumentProfile`

High-level description of the current document session.

It captures:

- session id
- document type
- document family
- page count
- extraction methods used
- whether PII was detected
- detected credential categories
- whether manual review is likely required
- analysis notes

### `ExtractedCredential`

Represents one extracted field, credential, claim, or identifier from a document.

It captures:

- stable credential id
- label and category
- raw and normalized value
- extraction confidence
- grounding location
- PII flag
- whether verification is required
- why the planner made that decision
- extraction method

### `VerificationTask`

Represents one deterministic verification task derived from an extracted credential.

It captures:

- task id
- referenced credential id
- selected verifier key and label
- verification type
- required flag
- planned task status
- reason codes
- minimal input payload for the verifier execution layer

### `VerifierRouteDecision`

Represents the router's deterministic placeholder decision for a credential.

It captures:

- selected verifier key
- verifier label
- route reason
- fallback verifier keys
- whether manual review is recommended

## Verifier Execution Contracts

The new `backend/app/verifier_execution/` module is the per-credential execution boundary.

It contains:

- bounded execution contracts
- verifier registry
- sequential task executor
- placeholder verifier implementations
- session-scoped persistence helpers

### `VerificationTaskResult`

Represents the execution outcome for one verification task.

It captures:

- task id
- credential id
- verifier key and label
- task execution status
- field-level audit status
- bounded outcome color
- explanation
- reason codes
- matched, mismatched, and missing fields
- raw result summary
- confidence
- executed timestamp
- latency
- manual review recommendation flag

Bounded task statuses used in this stage:

- `SUCCEEDED`
- `PARTIAL`
- `FAILED`
- `MANUAL_REVIEW`
- `SKIPPED`

### `CredentialVerificationBundle`

Represents all verifier attempts for one credential.

It captures:

- credential id
- label and category
- selected task ids
- number of results
- final audit status
- final outcome color
- explanation
- reason codes
- best result
- all results

### `SessionVerificationExecutionSummary`

Represents the session-scoped execution rollup.

It captures:

- total tasks
- succeeded tasks
- partial tasks
- failed tasks
- manual review tasks
- skipped tasks
- overall execution status
- verifier keys used
- start and completion timestamps

### `SessionVerificationExecutionStatus`

Represents the subordinate execution readiness state for UI and orchestration consumers.

It captures:

- session id
- main workflow state
- verification execution status
- verification execution error
- whether task results, bundles, and execution summary are available

Bounded execution statuses used in this stage:

- `NOT_STARTED`
- `RUNNING`
- `READY`
- `FAILED`

## Stable Audit Contract

### `CredentialAudit`

Represents field-level audit data for UI overlays, hover cards, and drill-down details.

It captures:

- document value and normalized value
- verifier label
- stable audit status
- bounded outcome color
- explanation and reason codes
- matched, mismatched, and missing fields
- evidence blocks from extraction, task execution, connectors, and trust output
- timestamp

Stable audit statuses:

- `VERIFIED`
- `MISMATCH`
- `PARTIAL`
- `UNVERIFIED`
- `MANUAL_REVIEW`
- `NOT_APPLICABLE`

Stable color mapping:

- `VERIFIED` -> `green`
- `MISMATCH` -> `red`
- `PARTIAL` -> `amber`
- `UNVERIFIED` -> `amber`
- `MANUAL_REVIEW` -> `amber`
- `NOT_APPLICABLE` -> `neutral`

## Generalized Analysis Service

`backend/app/verification_domain/service.py` remains the single place responsible for building and persisting generalized analysis artifacts.

Its audit assembly now prefers:

1. true task results and credential bundles
2. legacy connector or trust adaptation only when execution artifacts are absent

This keeps field-level audits honest while staying backward compatible with older sessions.

## Verifier Registry And Executor

`backend/app/verifier_execution/registry.py` maps `verifier_key` to a verifier implementation.

Current deterministic placeholder verifiers include:

- `identity_db`
- `address_check`
- `passport_db`
- `academic_registry`
- `certificate_registry`
- `license_registry`
- `financial_registry`
- `tax_authority`
- `manual_review`

Each verifier receives:

- one `VerificationTask`
- the corresponding `ExtractedCredential`
- session-scoped execution context

Each verifier returns one `VerificationTaskResult`.

The sequential executor in `backend/app/verifier_execution/executor.py` then builds:

- task results
- credential bundles
- execution summary

## Workflow Integration

The top-level workflow states remain unchanged.

Stage 4 integrates per-credential execution into the existing runtime as a subordinate layer:

1. extraction builds the document view
2. generalized Pass A persists profile, credentials, plan, and routes
3. current connector execution still runs as before
4. generalized verifier execution runs task-by-task using the persisted plan
5. legacy document-level trust evaluation still runs as before
6. generalized Pass B builds audits and summary, now preferring task results

This keeps document-level deterministic trust evaluation separate from field-level evidence generation.

## Read Endpoints

Generalized analysis endpoints:

- `GET /session/{session_id}/credentials`
- `GET /session/{session_id}/verification-plan`
- `GET /session/{session_id}/credential-audits`
- `GET /session/{session_id}/verification-summary`
- `GET /session/{session_id}/document-profile`
- `GET /session/{session_id}/analysis-status`

New execution endpoints:

- `GET /session/{session_id}/verification-task-results`
- `GET /session/{session_id}/credential-bundles`
- `GET /session/{session_id}/verification-execution-status`

These endpoints prefer persisted payloads and fall back to deterministic compute-on-read when possible.

## Provider Abstraction Note

Real provider-backed verifiers are intentionally deferred.

Future provider integrations should sit behind the verifier registry boundary so the repo does not lock into one provider.

Possible future provider-backed responsibilities include:

- PII-sensitive identity lookup
- academic registry federation
- certificate authority checks
- routing assistance
- explanation enrichment

Stage 4 does not make outbound provider calls.

## Stage Boundary

This stage does not:

- add LangGraph orchestration
- add unconstrained LLM reasoning
- replace deterministic trust scoring
- remove legacy routes or pages
- add mutation-heavy reviewer workflows
- add real external verifier credentials

Future stages can build on the persisted generalized and execution artifacts to support richer verifier fan-out, orchestration, and provider-backed execution without rewriting the current session flow.
