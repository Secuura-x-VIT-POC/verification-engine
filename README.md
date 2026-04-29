# Verification Engine

Generic PDF verification framework for session-scoped document review, connector validation, trust rendering, and secure cleanup.

## Product Direction

- The product is a generalized document verification platform, not a recruitment-only verifier.
- Microsoft Entra Verified ID is the primary VC and identity trust rail for Entra-aligned credentials.
- Other public or open verification APIs remain supplementary connectors.
- JWT login is acceptable for the current POC, while Microsoft Entra is the target identity and access model.

## Core Flow

1. Upload and view experience
   - Reviewers upload a PDF and open a bounded verification session.
   - Processing remains session-scoped and privacy-aware.
2. Extraction and grounding
   - The extraction service parses the document, grounds fields to page geometry, and produces reusable session artifacts.
   - OCR stays local by default with the precedence `native PDF text -> PaddleOCR -> Tesseract fallback`.
3. Connector validation
   - Deterministic planning builds per-credential verification tasks.
   - The verifier registry executes those tasks through Microsoft Entra Verified ID when available, then supplementary providers, then honest fallback paths.
4. Trust result rendering
   - The generalized workspace renders field-level audits and a consolidated deterministic trust outcome.
   - LangGraph enrichment can improve understanding and explanation, but it does not decide final trust.
5. Secure cleanup
   - Cleanup remains session-driven and minimizes retained content after review.

## Architecture Layers

- `backend/app/workflow/`: session runtime and existing top-level workflow state machine.
- `backend/app/verification_domain/`: generalized profile, credential, plan, audit, and summary contracts.
- `backend/app/verifier_execution/`: per-credential task execution and bundle assembly.
- `backend/app/verifier_providers/`: provider registry, capability policy, safe HTTP client, and provider adapters.
- `backend/app/agent_orchestration/`: bounded LangGraph enrichment for document understanding, grouping, routing assistance, and explanations.
- `backend/app/trust/`: deterministic document-level trust evaluation.
- `frontend/src/features/generalized-verification/`: generalized reviewer workspace.
- `frontend/src/pages/VerifyPage.jsx`: legacy page kept alive during migration.

## Trust Rail Precedence

- Microsoft Entra Verified ID is the primary path for VC-presentable identity, academic, and certificate-style credentials.
- Supplementary providers are used only when Entra is unavailable or not applicable.
- Manual review is the bounded fallback when executable evidence is insufficient.
- Deterministic trust remains the final document-level authority.

## Security and Privacy

- External verifier providers are optional and disabled by default.
- Full-document outbound transfer is not enabled by default.
- Payload minimization and redaction run before outbound provider calls.
- Technical traces persist redacted summaries only.
- Cleanup still purges derived artifacts with the source document state.

## Governance

- Secuura reviews the final architecture.
- Secuura owns the final architecture in alignment with its broader platform architecture.
- Future commercial rights remain with Secuura.

## Status

This repository is a POC implementation of the verification backbone and reviewer workspace. Stage 8 adds an explicit demo-mode transition layer so the repo can present Entra-first verification honestly before live tenant wiring exists. Mock paths remain available, demo mode is explicit, and the architecture remains aligned for later live Entra and supplementary-provider rollout.

## Docker Compose Quick Start

1. Copy `.env.example` to `.env`.
2. Set the secrets and optional provider keys you actually want to use.
3. Start the full stack:

```powershell
docker compose up --build
```

Default containerized behavior:

- PostgreSQL runs inside Compose.
- Compose includes a one-shot database bootstrap step, so reused Postgres volumes still get the configured app database if it is missing.
- The backend runs the full generalized verifier pipeline.
- OCR stays local inside the backend container.
- OCR precedence is `native PDF text -> PaddleOCR -> Tesseract fallback`.
- Local mock verification is enabled by default.
- Microsoft Entra Verified ID remains the preferred trust rail architecturally, but live outbound execution is disabled by default.
- Gemini/LangGraph enrichment is the active LLM path when `GEMINI_API_KEY` is configured; deterministic fallback remains available without a key.

Default local URLs:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Backend health: `http://localhost:8000/healthz`
- Backend readiness: `http://localhost:8000/readyz`

Notes:

- No host-side Python, Tesseract, or PaddleOCR install is required when running through Docker Compose.
- The local verification store is available inside the backend container at `/app/backend/app/verifier_providers/fixtures/local_verification_records.json` unless overridden by `VERIFIER_LOCAL_VERIFICATION_STORE_PATH`.
- That local verification store is mounted into the backend container from `backend/app/verifier_providers/fixtures/local_verification_records.json`, so updating the repo file updates the in-container truth store without rebuilding the image.
- Uploaded PDFs are stored in the `backend_uploads` named volume.

To confirm which OCR backend was actually used for a processed session:

1. Upload and verify a document.
2. Fetch the session payload:

```powershell
curl http://localhost:8000/sessions/<session_id>
```

3. Inspect `extraction.ocr_metadata.engine_used`, `extraction.ocr_metadata.engines_used`, and `extraction.ocr_metadata.fallback_used`.

Expected values:

- `engine_used: "native_text"` for text-rich PDFs
- `engine_used: "paddleocr"` for scanned pages when PaddleOCR handled OCR
- `engine_used: "tesseract"` only when PaddleOCR was unavailable or failed

## License

Internal POC - Secuura x VIT
