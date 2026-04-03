# Generalized Verification Contracts

## Purpose

This repository is a generalized document verification platform. The current architecture combines:

- deterministic extraction and session workflow
- generalized analysis contracts
- per-credential verifier execution
- provider-backed verifier integration
- a bounded LangGraph enrichment layer

The LangGraph layer exists to improve document understanding, credential grouping, route suggestions, and reviewer-facing explanations. It does not decide final trust, bypass verifier execution, or replace the deterministic trust engine.

## Persisted Session Artifact Families

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

### Provider execution artifacts

- `provider_execution_traces_payload`
- `provider_execution_status`
- `provider_execution_error`

### Agent orchestration artifacts

- `agent_document_understanding_payload`
- `agent_credential_candidates_payload`
- `agent_route_recommendations_payload`
- `agent_explanations_payload`
- `agent_run_summary_payload`
- `agent_run_status`
- `agent_run_error`

All artifact fields are additive, nullable, and backward compatible with older rows.

## Generalized Analysis Contracts

### `DocumentProfile`

Session-level document classification summary:

- document type and family
- page count
- extraction methods used
- detected categories
- PII detection
- manual-review hints
- notes

### `ExtractedCredential`

Field-level extracted data:

- stable credential id
- label and category
- raw and normalized value
- confidence
- source text
- page and bounding box
- PII flag
- verification requirement and reason
- extraction method

### `VerificationTask`

Deterministic verification work item:

- task id and credential id
- selected verifier key and label
- verification type
- required flag
- status
- reason codes
- bounded input payload

### `VerifierRouteDecision`

Deterministic or reconciled route selection:

- selected verifier key and label
- route reason
- fallback verifiers
- manual review recommendation

## Verifier Execution Contracts

The `backend/app/verifier_execution/` module is the field-level execution boundary.

### `VerificationTaskResult`

- task id
- credential id
- verifier key and label
- task status
- audit status
- outcome color
- explanation
- reason codes
- matched, mismatched, and missing fields
- raw result summary
- confidence
- execution time and latency
- manual review flag

Bounded task statuses:

- `SUCCEEDED`
- `PARTIAL`
- `FAILED`
- `MANUAL_REVIEW`
- `SKIPPED`

### `CredentialVerificationBundle`

- one credential id
- selected task ids
- result count
- final audit status
- final outcome color
- explanation
- best result
- all results

### `SessionVerificationExecutionSummary`

- total, succeeded, partial, failed, manual-review, and skipped task counts
- overall execution status
- verifier keys used
- start and completion timestamps

Execution status values remain bounded:

- `NOT_STARTED`
- `RUNNING`
- `READY`
- `FAILED`

## Verifier Provider Contracts

The `backend/app/verifier_providers/` module is the outbound verifier boundary.

### `ProviderCapability`

- provider key and label
- supported verifier keys and categories
- batch, partial-match, document-upload, and field-lookup support
- credential requirement flag
- default timeout
- enabled flag

### `ProviderRequest`

- request id
- session id
- task id
- verifier key and provider key
- minimized input payload
- redacted payload snapshot
- request mode
- timeout
- metadata

### `ProviderResponse`

- request id
- provider key
- bounded technical status
- HTTP status
- response summary
- raw result reference
- matched, mismatched, and missing fields
- confidence
- reason codes
- latency
- manual-review flag

### `ProviderExecutionTrace`

- request id
- provider key and verifier key
- start and completion timestamps
- bounded technical status
- redaction-applied flag
- outbound mode
- retry count
- error summary
- HTTP status
- redacted response summary
- fallback-used flag

Provider technical statuses remain bounded:

- `SUCCESS`
- `FAILED`
- `TIMEOUT`
- `DISABLED`
- `BLOCKED`
- `UNCONFIGURED`
- `SKIPPED`

## Agent Orchestration Contracts

The `backend/app/agent_orchestration/` module is the bounded enrichment layer.

### `AgentDocumentUnderstanding`

- document type guess
- document family guess
- confidence
- detected sections
- detected entities
- PII signals
- credential candidate ids
- reasoning summary
- manual review recommendation

### `AgentCredentialCandidate`

- candidate id
- label and inferred category
- source fields and grouped field ids
- grouped values
- confidence
- verification recommendation and reason
- possible verifier keys
- ambiguity flags

### `AgentRouteRecommendation`

- candidate id
- recommended verifier key
- alternative verifier keys
- route reason
- confidence
- manual review recommendation

### `AgentExplanationArtifact`

- target type and target id
- explanation kind
- summary
- structured reasons
- caution notes
- generation timestamp

### `AgentRunSummary`

- session id
- run status
- executed nodes
- provider used
- start and completion timestamps
- warnings
- fallback flag

Agent run statuses remain bounded:

- `NOT_STARTED`
- `RUNNING`
- `READY`
- `FAILED`

## LangGraph Structure

Stage 5 uses a bounded, linear LangGraph workflow:

1. `input_normalization`
2. `document_understanding`
3. `credential_grouping`
4. `route_recommendation`
5. `explanation_synthesis`
6. `output_consolidation`

There are no autonomous loops, no external tool invocation from the graph, and no trust-decision node.

## Provider Abstraction

Agent providers live under `backend/app/agent_orchestration/providers/`.

Current provider surface:

- `analyze_document(...)`
- `group_credentials(...)`
- `recommend_routes(...)`
- `generate_explanations(...)`

Current implementations:

- `DeterministicProvider`: default, local, test-safe, and enabled by default
- `NvidiaProvider`: stub only, disabled by default, selected only through config, and falls back to deterministic behavior when unavailable

Verifier providers live under `backend/app/verifier_providers/`.

Current verifier-provider surface:

- `get_capabilities(...)`
- `prepare_request(...)`
- `execute(...)`
- `normalize_response(...)`

Current verifier-provider implementations:

- `LocalMockProvider`: default local fallback, no network, no fake live evidence
- `IdentityHttpProvider`: optional HTTP JSON adapter for `identity_db`
- `AcademicRegistryHttpProvider`: optional HTTP JSON adapter for `academic_registry`

The verifier registry owns task semantics. Provider adapters only handle capability, outbound transport, and normalization.

## Runtime Integration

### Pass A

After extraction:

1. deterministic credentials and baseline plan are built
2. agent Pass A runs through LangGraph
3. route planning remains capability-aware and may reflect external-provider availability or bounded local fallback
4. agent outputs may refine category assignment and route selection only through bounded reconciliation
5. enriched generalized profile, credentials, and plan are persisted

### Pass B

After per-credential verifier execution:

1. verifier execution attempts provider-backed verification when safely enabled
2. provider traces are persisted without full raw payload retention
3. deterministic task results and bundles are assembled from normalized execution outputs
4. deterministic audits are built from real execution artifacts
5. agent Pass B synthesizes bounded explanation artifacts
6. agent explanations are merged into audits as clearly labeled reviewer-facing notes

## Precedence And Reconciliation Policy

The precedence model is explicit:

1. extracted document values, geometry, and session-scoped evidence remain source-of-record
2. agent outputs may enrich classification, grouping, route suggestions, and explanations
3. deterministic verifier execution performs the actual verification tasks
4. verifier providers may supply normalized field evidence but do not own trust policy
5. deterministic trust evaluation remains the final document-level authority

If agent and deterministic routing differ:

- both are recorded through task input payloads and route reasoning
- agent suggestions can only override a `manual_review` route through bounded reconciliation
- deterministic verified evidence is never replaced by agent guesses

## Read Endpoints

Generalized analysis:

- `GET /session/{session_id}/credentials`
- `GET /session/{session_id}/verification-plan`
- `GET /session/{session_id}/credential-audits`
- `GET /session/{session_id}/verification-summary`
- `GET /session/{session_id}/document-profile`
- `GET /session/{session_id}/analysis-status`

Verifier execution:

- `GET /session/{session_id}/verification-task-results`
- `GET /session/{session_id}/credential-bundles`
- `GET /session/{session_id}/verification-execution-status`

Provider execution:

- `GET /session/{session_id}/provider-execution-traces`
- `GET /session/{session_id}/provider-execution-status`
- `GET /session/{session_id}/provider-capabilities`

Agent orchestration:

- `GET /session/{session_id}/agent-document-understanding`
- `GET /session/{session_id}/agent-credential-candidates`
- `GET /session/{session_id}/agent-route-recommendations`
- `GET /session/{session_id}/agent-run-status`

These endpoints prefer persisted payloads and return safe structured responses for older or partially populated sessions.

## Security And Privacy Guardrails

- external agent providers are disabled unless explicitly enabled by config
- the default provider is deterministic and local
- external verifier providers are disabled unless explicitly enabled by config
- payload minimization and redaction run before outbound verifier calls
- full-document outbound transfer is not enabled by default
- allowlisted domains, bounded timeouts, retries, and size limits gate HTTP providers
- trace persistence stores redacted summaries and technical metadata only
- extraction payload minimization is applied before provider-facing graph state is built
- no full prompt or document dumps are written to logs
- agent failure is subordinate and does not break the core deterministic workflow
- provider technical failure is subordinate and falls back to bounded task outcomes such as `PARTIAL`, `UNVERIFIED`, or `MANUAL_REVIEW`
- cleanup still purges derived artifacts along with source document state

## Stage Boundary

Stage 5 adds LangGraph orchestration, but it still does not:

- let the agent decide final trust outcome
- remove deterministic planner/router/executor behavior
- require external provider keys for normal repo use
- add uncontrolled autonomous loops
- add reviewer mutation flows
- add real provider-backed verifier calls

Stage 6 adds provider-backed verifier plumbing, but it still does not:

- require external verifier credentials for normal repo use
- let providers bypass verifier normalization or trust policy
- upload full documents by default
- make outbound provider access mandatory

## Deferred To Stage 7

- richer provider-specific adapters beyond the initial HTTP examples
- explicit reviewer override flows around provider failures or manual review
- broader grouped-claim execution beyond the current per-credential backbone
- deeper multi-provider reconciliation and retry policy
- broader performance work for large document sessions and UI bundle size
