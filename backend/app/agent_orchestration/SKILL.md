# Agent Orchestration Module Guide

## Role

This module is the bounded LangGraph enrichment layer for:

- document understanding
- credential grouping
- verifier route assistance
- reviewer-facing explanation support

It does not decide final trust and does not replace deterministic verifier execution.

The product remains a generic PDF verification framework. Recruitment is only a sample use case. Microsoft Entra Verified ID is the primary VC trust rail for Entra-aligned credentials, while supplementary connectors remain additive.

## Design Rules

- Keep the graph bounded and linear.
- No autonomous loops.
- No direct workflow-state mutations from graph nodes.
- No silent provider fallback that hides warnings or policy decisions.
- Preserve deterministic extracted values and geometry as source-of-record.

## Provider Rules

- The deterministic provider is the default path.
- External providers must remain disabled by default.
- Any future real provider integration belongs behind `providers/`.
- Do not hardcode vendor-specific logic into node, workflow, or UI code.
- Verifier-provider execution is a separate layer under `backend/app/verifier_providers/` and must remain distinct from agent providers.
- Agent route assistance may point toward Entra-first verification, but final execution still flows through the deterministic verifier registry and provider capability checks.

## Reconciliation Rules

- Agent outputs may refine classification, grouping, routing, and explanation text.
- Deterministic verifier execution remains the execution authority.
- Deterministic trust remains the document-level authority.
- If uncertain, recommend manual review.
