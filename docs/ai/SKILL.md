# Generalized Verification Repo Guide

## Purpose
- This repository is a generalized document verification platform.
- It is no longer recruitment-only and should not be treated as resume-only logic.
- The platform accepts PDFs, extracts candidate credentials and claims, routes them for deterministic verification, and produces session-scoped audits plus consolidated outcomes.

## Current Architecture Layers
- `backend/app/workflow/`: existing session-driven verification runtime and state machine integration.
- `backend/app/verification_domain/`: generalized verification contracts, planner/router scaffolding, adapters, and persisted analysis services.
- `backend/app/verifier_execution/`: per-credential verifier contracts, registry, executor, placeholder verifiers, and persisted execution services.
- `backend/app/api/` and `backend/app/sessions/`: authenticated read and session lifecycle routes.
- `frontend/src/pages/VerifyPage.jsx`: legacy verification page that must remain alive during migration.
- `frontend/src/features/generalized-verification/`: new read-only generalized reviewer workspace built around persisted artifacts.

## Persisted Generalized Artifacts
- `document_profile_payload`
- `generalized_credentials_payload`
- `verification_plan_payload`
- `credential_audits_payload`
- `verification_summary_payload`
- `generalized_analysis_status`
- `generalized_analysis_error`

These are session-scoped additive artifacts and must remain backward compatible with older rows.

## Persisted Execution Artifacts
- `verification_task_results_payload`
- `credential_verification_bundles_payload`
- `verification_execution_summary_payload`
- `verification_execution_status`
- `verification_execution_error`

These are also additive session-scoped artifacts and must remain safe for older rows.

## Frontend Migration Rule
- The legacy verify page and route stay in place temporarily.
- New generalized reviewer work should go into the feature module under `frontend/src/features/generalized-verification/`.
- Additive migration is preferred over replacing existing reviewer flows in one step.

## Strict Constraints
- Do not break or rename the existing top-level workflow states.
- Do not replace the deterministic trust engine with unconstrained model reasoning.
- Keep the privacy-aware session model, cleanup flow, and session boundaries intact.
- Keep code modular, typed by contract shape, and easy to explain.
- Prefer additive changes over destructive rewrites.

## Backend Rules
- Reuse `backend/app/verification_domain/contracts.py` as the contract source of truth.
- Reuse `backend/app/verifier_execution/contracts.py` for task execution artifacts and bounded execution statuses.
- Keep generalized analysis deterministic unless a later stage explicitly changes that behind a clean interface.
- Do not fake verification success when connector evidence is absent.
- Route real per-credential execution through the verifier registry instead of scattering verifier logic through unrelated services.
- New backend helpers should be read-only and derived from persisted artifacts unless a later stage explicitly needs more.

## Frontend Rules
- Use feature-based modules with isolated API helpers, hooks, components, and mapping utilities.
- Do not pass raw backend payloads straight into presentational components when a view model keeps the UI clearer.
- Prefer graceful empty, loading, and partial-data states over brittle assumptions.
- Overlay logic must only use real bounding boxes; never invent geometry.

## Future Direction
- LangGraph-based agent orchestration is planned for a later stage and is intentionally deferred right now.
- Model/provider integrations must sit behind clean interfaces so the repo does not lock into one provider.
- Real provider-backed verifier implementations must go behind the verifier registry and execution boundary rather than bypassing it.
- Candidate future provider interfaces may assist with PII detection, credential classification, routing assistance, or explanation generation, but provider calls should stay out of the core workflow until explicitly introduced.

## Coding Conventions
- Additive changes preferred.
- Typed contracts and bounded status sets preferred.
- Feature-based UI modules preferred.
- Isolated API/data layers preferred.
- Small explainable components preferred.
