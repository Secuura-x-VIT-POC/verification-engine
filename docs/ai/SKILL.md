# Generalized Verification Repo Guide

## Purpose

- This repository is a generalized document verification platform.
- It must not be treated as recruitment-only, transcript-only, or passport-only.
- The platform accepts PDFs, extracts candidate credentials, builds bounded verification plans, executes per-credential verification, and produces session-scoped audits plus consolidated outcomes.

## Current Architecture Layers

- `backend/app/workflow/`: session-driven runtime, leases, retries, and the existing top-level state machine.
- `backend/app/verification_domain/`: generalized profile, credential, plan, audit, and summary contracts plus deterministic planning services.
- `backend/app/verifier_execution/`: per-credential verifier contracts, registry, executor, and placeholder verifiers.
- `backend/app/verifier_providers/`: provider contracts, secure outbound client, provider registry, redaction policy, and optional HTTP adapters.
- `backend/app/agent_orchestration/`: bounded LangGraph enrichment for document understanding, credential grouping, route assistance, and explanation support.
- `backend/app/api/` and `backend/app/sessions/`: authenticated read routes and session lifecycle.
- `frontend/src/pages/VerifyPage.jsx`: legacy verify page that must remain alive.
- `frontend/src/features/generalized-verification/`: additive generalized reviewer workspace.

## Persisted Artifact Families

### Generalized analysis

- `document_profile_payload`
- `generalized_credentials_payload`
- `verification_plan_payload`
- `credential_audits_payload`
- `verification_summary_payload`
- `generalized_analysis_status`
- `generalized_analysis_error`

### Verifier execution

- `verification_task_results_payload`
- `credential_verification_bundles_payload`
- `verification_execution_summary_payload`
- `verification_execution_status`
- `verification_execution_error`

### Provider execution

- `provider_execution_traces_payload`
- `provider_execution_status`
- `provider_execution_error`

### Agent orchestration

- `agent_document_understanding_payload`
- `agent_credential_candidates_payload`
- `agent_route_recommendations_payload`
- `agent_explanations_payload`
- `agent_run_summary_payload`
- `agent_run_status`
- `agent_run_error`

All of these are additive, nullable, and must remain backward compatible with older rows.

## Strict Constraints

- Do not break or rename the existing top-level workflow states.
- Do not replace the deterministic trust engine with unconstrained model reasoning.
- Do not bypass the verifier registry or per-credential execution layer.
- Do not bypass the verifier provider layer with ad hoc outbound requests.
- Keep the privacy-aware session model, cleanup flow, and session boundaries intact.
- Keep old routes/pages alive while migration continues.
- Keep code modular, bounded, typed, and explainable.

## Agent Layer Rules

- The agent role is understanding, grouping, route assistance, and explanation support.
- LangGraph orchestration is bounded and linear. No uncontrolled loops.
- Agent outputs enrich deterministic planning and reviewer context. They do not decide final trust.
- If uncertain, prefer manual review.
- Do not silently replace deterministic extracted values or geometry with model guesses.
- If agent and deterministic routing differ, record both or reconcile through explicit bounded logic only.
- Do not log full prompts, raw documents, or unnecessary sensitive content.

## Provider Rules

- External agent providers must be disabled by default unless explicitly enabled through config.
- The deterministic local provider is the default safe path for normal repo use and for tests.
- Any future real provider integration must sit behind `backend/app/agent_orchestration/providers/`.
- No provider-specific business logic should leak into workflow, planning, execution, or frontend code.
- No provider lock-in.

## Verifier Provider Rules

- External verifier providers must remain optional and disabled by default unless explicitly configured.
- The default verifier-provider path is `local_mock`, which is local-only and must not pretend to be live evidence.
- Real outbound verifier integrations belong under `backend/app/verifier_providers/`.
- Use the provider registry, policy loader, and safe HTTP client instead of making direct network calls.
- Do not log raw secrets, raw request bodies, or full sensitive provider responses.
- Do not send full documents externally unless a provider policy explicitly allows document upload.
- If provider capability is absent or execution fails, fall back honestly to `PARTIAL`, `UNVERIFIED`, or `MANUAL_REVIEW`.

## Backend Conventions

- Reuse `backend/app/verification_domain/contracts.py` for generalized artifacts.
- Reuse `backend/app/verifier_execution/contracts.py` for execution artifacts and bounded statuses.
- Reuse `backend/app/verifier_providers/contracts.py` for provider capability, request, response, and trace artifacts.
- Reuse `backend/app/agent_orchestration/contracts.py` for agent artifacts and bounded run statuses.
- Prefer service boundaries over scattered orchestration logic.
- Keep deterministic fallbacks available even when agent enrichment exists.
- Do not fake verification success when evidence is absent.

## Frontend Conventions

- Use feature-based modules with isolated API helpers, hooks, components, and mapping utilities.
- Do not pass raw backend payloads directly into presentational components when a view model keeps the UI clearer.
- Label agent-assisted content honestly in the UI.
- Overlay logic must only use real bounding boxes. Never invent geometry.
- Prefer stable empty, loading, and partial-data states.

## Migration Rule

- The legacy verify flow and the generalized workspace must coexist during migration.
- Additive changes are preferred over rewrites.
- New generalized UI work belongs under `frontend/src/features/generalized-verification/`.

## Future Direction

- Real provider-backed agent integrations are deferred to a later stage.
- Broader verifier-provider coverage beyond the initial HTTP adapters is deferred.
- Reviewer override and mutation flows are deferred.
- Grouped-claim execution beyond the current per-credential backbone is deferred.
- Deterministic trust remains the final document/session authority unless an explicitly bounded later stage changes that contract.
