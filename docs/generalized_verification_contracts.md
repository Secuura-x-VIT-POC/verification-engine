# Generalized Verification Contracts

## Purpose

This repository is a generalized document verification platform. The current architecture combines:

- deterministic extraction and session workflow
- generalized analysis contracts
- per-credential verifier execution
- provider-backed verifier integration
- a bounded LangGraph enrichment layer

Microsoft Entra Verified ID is the primary VC and identity trust rail for Entra-aligned credentials. Supplementary public or open verification APIs remain additive connectors behind the same verifier-provider boundary.

The LangGraph layer exists to improve document understanding, credential grouping, route suggestions, and reviewer-facing explanations. It does not decide final trust, bypass verifier execution, or replace the deterministic trust engine.

Optional NVIDIA-hosted inference now sits behind that bounded architecture:

- `minimaxai/minimax-m2.5` for agent reasoning
- `nvidia/gliner-pii` for PII and field-candidate enrichment

These integrations are config-driven, privacy-minimized, and must fall back to deterministic local behavior if disabled, unconfigured, or unavailable.

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
- `provider_operating_mode`
- `demo_profile_key`
- `execution_environment_label`
- `provider_transition_notes`

### Agent orchestration artifacts

- `agent_document_understanding_payload`
- `agent_credential_candidates_payload`
- `agent_route_recommendations_payload`
- `agent_explanations_payload`
- `agent_run_summary_payload`
- `agent_run_status`
- `agent_run_error`

All artifact fields are additive, nullable, and backward compatible with older rows.

## Primary Extraction Rule

Generalized analysis is now the default extraction contract for downstream planning and audit rendering.

- `field_candidates`
- `generalized_analysis`
- grounded evidence lines and spatial metadata

The older five-field compatibility schema (`Candidate Name`, `Institution`, `Credential`, `Issue Date`, `Document ID`) may still exist inside bounded trust-only compatibility surfaces, but it is no longer an active source for generalized credential discovery, verification planning, or audit rendering.

Field provenance precedence is now explicit:

- value span match on the same line is the primary evidence path
- tight label-plus-value context is preserved as supporting evidence
- nearby-right and nearby-below binding are bounded fallbacks only when the value line matches the expected semantic category
- local pattern matches without label support are retained, but they carry lower provenance confidence than label-bound matches
- extracted fields preserve source type metadata so downstream consumers can distinguish native PDF text, PaddleOCR, Tesseract, and mixed interpretation paths

Semantic extraction precedence is now explicit as well:

- deterministic document-family-aware rules lead semantic label assignment
- Aadhaar, PAN, report-card, marksheet, transcript, and generic identity cues narrow fields before generic labels are emitted
- generic outputs such as `date`, `document_number`, and `government_identifier` are last-resort labels when local context cannot safely narrow them further
- NVIDIA GLiNER may refine generic candidates, but it does not override stronger deterministic family-aware semantics

## Local OCR Boundary

OCR remains local and privacy-preserving by default.

- native PDF text extraction runs first
- PaddleOCR is the preferred local OCR backend for scanned or image-heavy pages when it is installed and enabled
- Tesseract remains a bounded local fallback of last resort
- NVIDIA models are not used for OCR and do not receive page images

The extraction payload may now include `ocr_metadata` with:

- backend mode
- OCR engine used
- whether native text and OCR were both used
- fallback-used flag
- average OCR confidence
- preprocessing steps applied
- page-level OCR metadata and warning codes

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

### `FieldCandidate`

Extraction-stage grounded field candidate:

- stable candidate id
- label and category
- raw and normalized value
- `source_text` anchored to the value span when available
- `evidence_snippet` preferring value span first, then tight label-plus-value context
- page, primary `bounding_box`, and optional `context_bounding_box`
- `grounding_match_type`
- `provenance_method`
- `provenance_confidence`
- `source` and `source_engine`
- extraction method

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
- planner-side `planning_status`
- `verification_recommended`
- `eligibility_reason`
- optional `grouping_reason`
- `source_candidate_ids`

Planner rule:

- not every extracted field becomes a verification credential
- only planner-promoted `verification_eligible` items enter route planning and task creation
- weak fields such as generic names, issuers, credential titles, weak dates, and weak identifiers are retained as context or metadata instead of first-class verification targets

### `CredentialAudit`

Field-level audit output is now strict about evidence scope:

- task results only attach when the `task_id` and `credential_id` belong to that credential
- extraction evidence stays local to the credential’s own value, page, and bounding box
- provider and connector summaries are attached only when they contain field-local matched or mismatched evidence for that credential
- route metadata may appear as minimal planning context, but it is not proof of verification
- document-level trust outcome and session-wide connector state remain in summary-level payloads and are not repeated as per-field audit evidence by default

Audit evidence precedence is now:

- field-local verification task result
- field-local extraction provenance
- field-local provider or connector response summary
- credential-scoped agent explanation
- minimal route metadata

### `SessionCredentialCollection`

Credential planning output now separates:

- `credentials`: verification-grade credentials that feed routing, tasks, audits, and execution
- `context_fields`: demoted but still preserved context/metadata fields that remain available for later UI and audit improvements
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
- preferred provider key and label
- planned provider key and label
- planned execution mode
- planned live/mock/demo flags
- bounded fallback reason when preferred and planned execution differ
- fallback verifiers
- manual review recommendation

## Verifier Execution Contracts

The `backend/app/verifier_execution/` module is the field-level execution boundary.

### `VerificationTaskResult`

- task id
- credential id
- verifier key and label
- preferred provider key and label
- planned provider key and label
- executed provider key and label
- explicit execution mode
- bounded fallback reason
- live/mock/demo result flags
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

Execution truth is now explicit:

- Entra may remain the preferred rail even when it does not execute
- the planned provider is the environment-real execution path selected during routing
- the executed provider is the provider that actually returned evidence for the task
- local rule-only fallback after a provider failure is labeled as fallback, not as successful provider execution
- local mock, demo, supplementary, and live provider outcomes are distinct in result metadata and audit evidence

## NVIDIA Inference Boundary

The shared `backend/app/inference/` module is the optional outbound model boundary.

- `NVIDIA_API_KEY`
- `NVIDIA_BASE_URL` with default `https://integrate.api.nvidia.com/v1`
- `NVIDIA_REASONING_MODEL` with default `minimaxai/minimax-m2.5`
- `NVIDIA_PII_MODEL` with default `nvidia/gliner-pii`
- `AGENT_PROVIDER=nvidia`
- `AGENT_EXTERNAL_PROVIDER_ENABLED=1`

Bounded precedence remains:

- deterministic extracted text and geometry stay source-of-record
- GLiNER may enrich label and category typing for field candidates
- MiniMax may improve document understanding, grouping, routing suggestions, and explanation text
- deterministic verifier execution decides field-level verification
- deterministic trust remains the final document-level authority
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
- current operating mode
- execution environment label
- demo-support flag

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
- provider operating mode
- demo profile key
- execution environment label
- transition notes
- mock, demo, and live result flags

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
- provider operating mode
- demo profile key
- execution environment label
- transition notes

### `ProviderTransitionConfig`

- preferred provider rail
- active provider operating mode
- enabled provider modes
- optional demo profile key
- live-provider-enabled flag
- fallback policy
- manual-review policy
- execution environment label
- provider transition notes

### `SessionProviderOperatingMode`

- session id
- workflow state
- provider operating mode
- execution environment label
- active demo profile key
- preferred provider rail
- enabled provider modes
- live-provider-enabled flag
- fallback policy
- manual-review policy
- provider transition notes

Provider technical statuses remain bounded:

- `SUCCESS`
- `FAILED`
- `TIMEOUT`
- `DISABLED`
- `BLOCKED`
- `UNCONFIGURED`
- `SKIPPED`

Provider operating modes remain bounded:

- `DEMO_MOCK`
- `LOCAL_MOCK`
- `EXTERNAL_CONFIGURED`
- `LIVE_DISABLED`
- `MANUAL_ONLY`

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
- `EntraVerifiedIdProvider`: optional Microsoft Entra Verified ID adapter for VC-presentable identity, academic, and certificate-style credentials
- `IdentityHttpProvider`: optional supplementary HTTP JSON adapter for `identity_db`
- `AcademicRegistryHttpProvider`: optional supplementary HTTP JSON adapter for `academic_registry`

Stage 8 adds a demo-profile layer behind the same provider contracts so Entra-aligned and supplementary provider paths can return deterministic seeded outputs without pretending that live tenant execution happened.

The verifier registry owns task semantics. Provider adapters only handle capability, outbound transport, and normalization.

## Runtime Integration

### Pass A

After extraction:

1. deterministic credentials and baseline plan are built
2. agent Pass A runs through LangGraph
3. route planning remains capability-aware, prefers Microsoft Entra Verified ID for Entra-aligned credentials, and records when supplementary or local fallback paths are used instead
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
4. Microsoft Entra Verified ID is the primary provider path for VC-presentable identity and credential classes when enabled
5. supplementary verifier providers may supply normalized field evidence but do not own trust policy
6. deterministic trust evaluation remains the final document-level authority

If agent and deterministic routing differ:

- both are recorded through task input payloads and route reasoning
- agent suggestions can only override a `manual_review` route through bounded reconciliation
- deterministic verified evidence is never replaced by agent guesses
- provider preference metadata records when Entra was preferred but unavailable
- route metadata, task results, and audit evidence all distinguish preferred provider, planned provider, and executed provider
- local mock and demo execution remain available, but they are labeled explicitly and never presented as live Entra verification

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
- `GET /session/{session_id}/provider-operating-mode`
- `GET /session/{session_id}/demo-profile`

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
- Microsoft Entra Verified ID is optional in the repo and must be explicitly configured before any outbound Entra call is attempted
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

Stage 8 adds a demo-hardened mock-to-live transition layer, but it still does not:

- require live Entra credentials for normal repo use
- label demo-mode provider responses as live
- add a broad admin control surface
- remove supplementary connectors
- replace the deterministic trust engine

## Entra Alignment Notes

- Microsoft Entra Verified ID is the explicit primary trust rail for VC-presentable identity, academic, and certificate-style credentials.
- Supplementary providers remain available for categories or environments where Entra is not executable.
- JWT-based login remains acceptable for the current POC, but Microsoft Entra is the target identity and access model.

## Deferred To Stage 9

- real tenant-specific Microsoft Entra Verified ID configuration and presentation templates
- broader supplementary provider adapters beyond the current examples
- explicit reviewer override flows around provider failures or manual review
- broader grouped-claim execution beyond the current per-credential backbone
- deeper multi-provider reconciliation and retry policy
- broader performance work for large document sessions and UI bundle size
