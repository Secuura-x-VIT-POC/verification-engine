# Actual Project Working

This document describes what the current codebase actually does on April 3, 2026. It is intentionally implementation-first. Where repo docs or naming imply a richer system, this document treats code execution as the source of truth.

## Scope And Method

- Source of truth: backend, extraction, provider, agent, and frontend code in the current `test` branch.
- Validation method: file inspection plus direct sample execution against `frontend/public/sample.pdf` and targeted service helpers.
- Goal: describe the real upload-to-render path, actual payload shapes, actual routing and fallback rules, and the main breakpoints causing weak extraction, validation, and auditing.
- Instrumentation added for this investigation: none.

## Runtime Reality

### Main API entry points

- Upload/session lifecycle starts in `backend/app/sessions/routes.py`.
- Legacy verify flow starts in `backend/app/api/routes.py` via `POST /session/{session_id}/verify`.
- Generalized workspace data is served by many `GET /sessions/{session_id}/...` endpoints in:
  - `backend/app/verification_domain/service.py`
  - `backend/app/verifier_execution/service.py`
  - `backend/app/agent_orchestration/service.py`

### Important reality: synchronous verify path is the active path

The request path from the frontend calls `run_verification` directly inside the API route. The lease-based worker/orchestrator flow exists in:

- `backend/app/workflow/service.py`
- `backend/app/workflow/repository.py`
- `backend/app/orchestrator/orchestrator.py`

but the current API path does not use that background runner.

### Important reality: environment loading is container-dependent

- The Python code does not auto-load `.env`.
- `docker-compose.yml` injects `.env` values into the backend container.
- This means direct local Python runs can behave differently from Docker Compose runs.
- In the shipped compose configuration, verifier provider mode defaults to `LOCAL_MOCK` if `VERIFIER_PROVIDER_OPERATING_MODE` is unset.
- In direct Python runs without exported env vars, provider mode falls back differently and agent/provider behavior can downgrade to deterministic/local defaults.

## End-To-End Flow

## 1. Upload And Session Flow

### Entry files

- `backend/app/sessions/routes.py`
- `backend/app/sessions/models.py`
- `backend/app/sessions/constants.py`

### Actual request flow

1. `POST /sessions`
2. `POST /sessions/{id}/upload-token`
3. `POST /upload`
4. `POST /session/{id}/verify`

### What actually happens

`create_session` inserts a session row with:

- `status = "CREATED"`
- default/null extraction, trust, audit, generalized, provider, and agent fields

`create_upload_token` issues a short-lived DB-backed upload token.

`upload_pdf` does all of the following:

- validates the token and session ownership
- performs PDF validation through `backend/app/security/pdf_validator.py`
- writes the file to `uploads/<uuid>.pdf`
- stores `pdf_path`, `mime_type`, and optional original filename
- resets most derived JSON columns to `NULL`
- sets `status = "UPLOADED_PENDING_REVIEW"`
- deletes the used upload token

### Persisted session fields after upload

The upload path clears most derived fields, including:

- `extraction`
- `trust`
- `audit`
- `connector_results`
- `provider_task_results`
- `provider_execution_summary`
- `provider_traces`
- `agent_*` fields
- `generalized_*` fields

### Important cleanup reality

`close_session` removes the uploaded PDF and clears many JSON payloads, but it does not fully wipe all higher-level trust/audit metadata. Notably, the row can retain fields such as:

- `trust_outcome`
- `reason_codes`
- `connector_ids`
- `document_commitment`
- `audit_receipt_id`

Audit DB rows also remain outside the session JSON.

## 2. Legacy Verification Runtime Flow

### Entry files

- `backend/app/api/routes.py`
- `backend/app/workflow/runtime.py`

### Actual call chain

`POST /session/{id}/verify` calls:

- `run_verification(...)` in `backend/app/workflow/runtime.py`

`run_verification` performs, in order:

1. session state transition to `VERIFYING`
2. document extraction
3. trust input construction
4. connector input construction
5. connector calls
6. trust evaluation
7. audit payload generation
8. session update with legacy payloads and top-level summary fields
9. state transition to `VERIFIED`

### Important state-machine bug

The route currently allows requests when the session is already `VERIFYING`, but `run_verification` itself immediately attempts a `VERIFYING` transition. If the route is hit in that state, the state machine can reject the second transition.

### What `run_verification` persists

The legacy runtime writes:

- `extraction`
- `trust`
- `audit`
- `connector_results`
- `status = VERIFIED`
- top-level trust summary fields such as `trust_outcome`, `reason_codes`, `connector_ids`
- audit receipt identifiers/commitments

This is the only place where the nested legacy `session.extraction`, `session.trust`, and `session.audit` payloads are written as one synchronous end-to-end pipeline.

## 3. Extraction And OCR Flow

### Entry files

- `extraction/parser/document_parser.py`
- `extraction/ocr/engine.py`
- `extraction/analysis/pipeline.py`
- `extraction/analysis/nvidia_enrichment.py`
- `extraction/schema/models.py`

### Actual extraction path

`workflow.runtime.extract_document_payload` calls:

- `extract_document_data_with_strategy(pdf_path, strategy=...)`

That function always starts with native parsing first.

### Actual native-vs-OCR decision

`document_parser.py`:

- extracts native PDF text first
- evaluates whether the document appears scanned or text-sparse
- only then runs hybrid OCR if needed

Per-page hybrid logic prefers native text unless the page looks sparse. Sparse page heuristics are based on thresholds such as low word count or low character density.

### OCR backend precedence

`extraction/ocr/engine.py` currently behaves like this:

- `AUTO` or `PADDLE_PREFERRED`: try PaddleOCR first, then Tesseract
- `TESSERACT_ONLY`: use Tesseract only
- `NATIVE_ONLY`: skip OCR entirely

### Actual persisted extraction sources

The extraction payload carries:

- normalized field summaries
- detailed field objects with source text and bounding boxes when available
- OCR metadata describing whether OCR ran and what backend was used
- analysis artifacts generated by `extraction/analysis/pipeline.py`

### Security/scanning reality

There are two different validation layers in the repo:

- `backend/app/security/pdf_validator.py`
- `extraction/security/validator.py`

The upload route uses the backend validator, not the stronger extraction-side validator. Malware scanning is environment-limited. If `clamscan` is unavailable, the backend validator falls back to SHA256 blocklist checks rather than real antivirus scanning.

## 4. Generalized Analysis Flow

### Extraction-layer analysis

`extraction/analysis/pipeline.py` runs after text extraction and builds:

- `evidence_lines`
- `field_candidates`
- extraction-layer `generalized_analysis`

This extraction-layer `generalized_analysis` already contains:

- document profile
- credential candidates
- verification plan
- audit-like structures
- summary data

### Important reality: there is a second semantic mapping layer

The backend does not simply expose extraction-layer credentials directly.

Instead, `backend/app/verification_domain/planner.py` rebuilds credentials from extracted fields and field candidates through `build_extracted_credentials(...)`.

This means there are two semantic interpretation stages:

1. extraction-layer field candidate generation
2. backend credential/category reclassification

This second pass materially changes routing behavior.

## 5. Credential Planning And Verifier Routing

### Entry files

- `backend/app/verification_domain/service.py`
- `backend/app/verification_domain/planner.py`
- `backend/app/verification_domain/adapters.py`
- `backend/app/verification_domain/routing.py`

### Actual planning flow

Generalized workspace endpoints call service functions such as:

- `get_credentials_for_session`
- `get_verification_plan_for_session`
- `get_credential_audits_for_session`
- `get_verification_summary_for_session`

Those services rebuild artifacts from the session and extraction payload when needed. They are not pure readers of persisted generalized JSON.

### Actual route selection

Planner output creates extracted credentials and route decisions. Routing uses category-based logic, mainly through `routing.py`.

For some categories such as `identity`, `academic`, and `certificate`, the route metadata records:

- `preferred_provider_key = "entra_verified_id"`

However, the actual executable provider is separately chosen from available providers. In common repo runtime modes, this becomes:

- `planned_provider_key = "local_mock"`

### Important reality: Entra is usually preference metadata, not the executed rail

The route record may say Entra is preferred while the execution plan still uses `local_mock`. This is the normal outcome when Entra is unavailable, disabled, or not active in the current provider operating mode.

## 6. Verifier Execution And Provider Flow

### Entry files

- `backend/app/verifier_execution/service.py`
- `backend/app/verifier_execution/executor.py`
- `backend/app/verifier_execution/adapters.py`
- `backend/app/verifier_execution/registry.py`
- `backend/app/verifier_providers/service.py`
- `backend/app/verifier_providers/providers/local_mock.py`
- `backend/app/verifier_providers/providers/entra_verified_id.py`

### Actual execution model

The generalized workspace reads task results and provider summaries from service endpoints. Those service functions can recompute execution outputs from the current session state and route plan.

The execution path is a combination of:

- connector-aware verifier logic
- provider runtime selection
- local mock/provider adapters
- fallback execution logic

### Important reality: connector evidence runs before provider-specific verifier logic

The category-specific verifier implementations contain `execute_without_connector(...)` branches, but the connector-aware execution layer checks connector-derived evidence first and then uses provider runtime. In practice, current behavior is dominated by:

- connector claim matching
- provider `local_mock`

The category-specific no-connector logic is not the dominant path in normal runs.

## Actual Contract Map

The shapes below reflect the current implementation, not aspirational contracts.

## 1. Session Extraction Payload

### Legacy persisted payload

The legacy `session.extraction` payload written by `run_verification` has a view-oriented shape similar to:

```json
{
  "document_type": "transcript",
  "used_ocr": false,
  "fields": {
    "credential-title": "BTech",
    "issuer": "VIT",
    "name": "John Doe"
  },
  "field_details": [
    {
      "key": "credential-title",
      "label": "Credential Title",
      "value": "BTech",
      "page": 1,
      "bbox": [120, 220, 260, 246],
      "source_text": "BTech"
    }
  ],
  "ocr_metadata": {
    "used_ocr": false,
    "backend": "native"
  }
}
```

The exact keys depend on canonicalization in `document_parser._build_canonical_schema`.

### Important limitation

The legacy view only exposes a small canonical field surface. It is not a faithful dump of all extraction-layer candidates.

## 2. `field_candidates`

Current extraction-layer field candidates resemble:

```json
[
  {
    "label": "name",
    "value": "John Doe",
    "normalized_value": "john doe",
    "confidence": 0.93,
    "page": 1,
    "bbox": [96, 142, 242, 168],
    "source_text": "John Doe",
    "source_line": "Name: John Doe",
    "source": "deterministic"
  }
]
```

Important realities:

- candidate labels are generated largely by deterministic regex and keyword rules
- generic labels are common
- not every candidate survives later credential transformation
- bounding boxes are only as good as the OCR/native line anchoring

## 3. Generalized Credentials

Backend planner credentials resemble:

```json
{
  "credential_id": "cred_1",
  "label": "credential_title",
  "value": "BTech",
  "normalized_value": "btech",
  "category": "academic",
  "document_type": "transcript",
  "issuer": "VIT",
  "holder_name": "John Doe",
  "page": 1,
  "bbox": [120, 220, 260, 246],
  "source_text": "BTech",
  "confidence": 0.93,
  "evidence": {
    "field_candidate_labels": ["credential", "credential_title"]
  }
}
```

### Important limitation

Category assignment is strongly keyword-driven. A field can be routed as a full academic credential even when it is only one extracted semantic fragment.

## 4. Verification Plan

Current plan items contain route metadata similar to:

```json
{
  "credential_id": "cred_1",
  "verifier_key": "academic_registry",
  "category": "academic",
  "preferred_provider_key": "entra_verified_id",
  "planned_provider_key": "local_mock",
  "reason_codes": [
    "CATEGORY_ACADEMIC",
    "ENTRA_PREFERRED_ROUTE",
    "LOCAL_PROVIDER_FALLBACK"
  ]
}
```

This is the clearest place where preferred-vs-actual execution diverges.

## 5. Verification Task Result

Task results currently look roughly like:

```json
{
  "credential_id": "cred_1",
  "task_status": "PARTIAL",
  "provider_key": "local_mock",
  "verifier_key": "academic_registry",
  "match_status": "unverified",
  "matched_fields": [],
  "mismatched_fields": [],
  "manual_review_reasons": [],
  "notes": ["No local record matched the candidate"],
  "raw_result": {
    "status": "unverified"
  }
}
```

Observed status families include:

- `verified`
- `mismatch`
- `manual_review`
- `unverified`

## 6. Credential Audit

Current audit items are assembled with a shape like:

```json
{
  "credential_id": "cred_1",
  "label": "credential_title",
  "status": "VERIFIED",
  "summary": "Matched against connector or provider evidence",
  "evidence": [
    {
      "type": "document_extraction",
      "detail": {
        "value": "BTech",
        "source_text": "BTech",
        "bbox": [120, 220, 260, 246]
      }
    },
    {
      "type": "connector_response",
      "detail": {
        "connector_id": "vit_registry",
        "status": "MISMATCH"
      }
    },
    {
      "type": "trust_result",
      "detail": {
        "outcome": "RED"
      }
    },
    {
      "type": "verification_task_result",
      "detail": {
        "provider_key": "local_mock",
        "match_status": "verified"
      }
    }
  ]
}
```

### Important limitation

Evidence is broad and often not field-specific. Global connector and trust artifacts are attached to every audit card.

## 7. Provider Response Summary

Provider summary/status endpoints expose values such as:

```json
{
  "provider_operating_mode": "LOCAL_MOCK",
  "execution_status": "READY",
  "provider_keys_used": ["local_mock"],
  "transition_notes": [
    "Local mock mode is active. No external provider calls will be attempted."
  ]
}
```

## 8. Frontend Workspace View Model

`frontend/src/features/generalized-verification/utils/viewModels.js` merges many endpoint responses into a UI model that contains:

- session overview
- analysis rows
- audit detail cards
- document highlights
- provider summaries
- agent recommendations

### Important reality

If audits are missing, the frontend fabricates fallback audit rows from extracted credentials. This means the UI can display audit-looking content even when no true field-level audit has been persisted.

## Weak Area A: PII Extraction

## What code identifies PII today

Primary code:

- `extraction/analysis/pipeline.py`
- `extraction/analysis/nvidia_enrichment.py`

The deterministic pipeline labels entities using configured label specs, regexes, and line-pattern heuristics. It creates field candidates from extracted text lines and spans.

## What text sources it uses

PII extraction uses the text produced by:

- native PDF parsing first
- hybrid OCR only when native text is sparse/scanned

Bounding boxes and source lines come from whichever text source won the parser stage for that line/page.

## How labels are assigned

Deterministic labeling is driven by `LABEL_CONFIG` and matching rules in `pipeline.py`.

Observed generic mappings include:

- `date` -> `date_reference`
- `document_id` -> `document_number`
- `government_identifier` -> `national_identifier`

These generic buckets are not deeply document-family-specific. They are broad semantic aliases from deterministic rules.

## How document family affects extraction

Document family influence is weak.

It mostly affects:

- document profiling
- verifier suggestion hints
- some categorization logic

It does not drive a deeply specialized extractor per document family.

## Where NVIDIA GLiNER enrichment is actually used

`nvidia_enrichment.py` defines entity specs and an enrichment pass that can add or refine PII candidates when NVIDIA enrichment is enabled and configured.

The GLiNER-style enrichment is an augmentation layer on top of deterministic extraction. It is not the base extractor.

## Fallback behavior if NVIDIA is off or fails

If NVIDIA enrichment is unavailable or fails:

- deterministic extraction still runs
- enrichment metadata records fallback/warning conditions
- the pipeline continues without enriched entities

### Important metadata bug

The enrichment metadata can still report `pii_provider = "nvidia"` and a configured `pii_model_used` even when no successful NVIDIA call happened. This makes provenance look stronger than it is.

### Sample-observed PII weakness

On the sample PDF:

- deterministic extraction produced only a narrow set of usable semantic fields
- the sample date string in ISO format was not extracted because the current date regexes miss that pattern
- generic overproduction risk remains high when documents contain many dates, ids, or official-looking number strings

## Weak Area B: Validation

## How credentials become verification tasks

Flow:

1. extraction produces fields and candidates
2. planner transforms them into generalized credentials
3. routing assigns verifier/provider metadata
4. execution services derive task results from connector evidence and provider results

Primary files:

- `backend/app/verification_domain/planner.py`
- `backend/app/verification_domain/routing.py`
- `backend/app/verifier_execution/service.py`

## How route selection happens

Route selection is category-driven. The planner classifies each credential and chooses a verifier class plus provider preference/fallback metadata.

### Important semantic weakness

`classify_credential_category` is heavily keyword-based. In practice this can produce:

- `credential_title` -> `academic`
- `issuer` -> `certificate`
- `person_name` -> `identity`

Those are not always wrong as labels, but they are too coarse to serve as strong standalone verification tasks. The routing layer treats them as if they were verification-grade credentials.

## When local mock validation runs

In normal compose-style runtime, local mock validation is the dominant provider path because:

- provider operating mode defaults to `LOCAL_MOCK`
- external provider execution is often disabled
- preferred Entra routing does not force Entra execution

## How local records are matched

`backend/app/verifier_providers/providers/local_mock.py` applies this rough sequence:

1. filter candidate records by compatible verifier/category/document type
2. prefer exact label-plus-value matches
3. then exact normalized value matches
4. if one comparable candidate disagrees, return `mismatch`
5. if many conflicting comparable candidates exist, return `manual_review`
6. if a candidate exists but comparison value is weak/missing, return `manual_review`
7. if no usable record matches, return `unverified`

### Important reality

`record not found` does not become a hard failure. It usually becomes an `unverified` task outcome that still looks structurally successful.

## What causes mismatch vs verified vs manual review

Observed local mock/result logic:

- `verified`: normalized value aligns with an eligible record
- `mismatch`: a comparable record exists but the value conflicts
- `manual_review`: ambiguous/conflicting candidates or insufficient comparable value
- `unverified`: nothing matched strongly enough

At the task level, this later maps into statuses such as green/amber/red in audit and summary transforms.

## Where Entra preference is only metadata

There are two different truths:

- planning metadata can declare Entra as the preferred route
- actual execution often uses `local_mock`

The legacy `run_verification` path does not invoke Entra at all. It only uses the VIT connector/trust flow for connector-backed verification.

## Connector/trust validation reality

`workflow/runtime.py` still builds legacy alias inputs:

- `name`
- `institution`
- `credential`
- `date`
- `id`

Connector use is narrow:

- `build_connector_responses` only calls the VIT connector when the institution contains `vit` and name plus degree are present

There is an Entra mock connector in the repo broker, but the active legacy verify flow does not use it.

## Sample-observed validation weakness

On the sample PDF:

- extracted connector input was `{name:"John Doe", degree:"BTech", institution:"VIT", document_id:""}`
- the VIT connector returned overall `MISMATCH`
- trust outcome became `RED`
- yet one field-level audit still became `VERIFIED` because a single claim-level match (`degree`) was treated as field verification

That is a direct implementation-level inconsistency between connector outcome and audit card outcome.

## Weak Area C: Auditing

## How audits are assembled

Primary files:

- `backend/app/verification_domain/adapters.py`
- `backend/app/audit/service.py`
- `backend/app/audit/receipt_generator.py`

The generalized audit path adapts extracted credentials, connector results, trust results, and provider task results into audit items.

The legacy audit receipt path separately builds the persisted receipt bundle used by the old verify page.

## What evidence is attached

Current generalized audit assembly attaches broad evidence types such as:

- document extraction
- connector response
- trust result
- verification task result

### Important reality

`_build_base_evidence` attaches all connector responses and the overall trust result to every audit item. Evidence is not tightly scoped to the exact field that the card represents.

## Where `source_text`, `bbox`, and `value` come from

These values ultimately originate from document extraction artifacts:

- native text parsing or OCR line extraction
- field candidate selection
- credential transformation

By the time they reach audit cards, they are often attached to broader connector/trust evidence that did not come from the same localized span.

## How task results become audit cards

The adapters combine:

- extracted credential
- connector matching heuristics
- trust outcome
- provider task result

to synthesize a final card status.

### Important reality

A connector with an overall `MISMATCH` can still yield a `VERIFIED` field card if one claim key lines up. That makes the card semantically stronger than the overall evidence warrants.

## Why misleading evidence can appear

There are three main reasons:

1. evidence is attached globally rather than field-specifically
2. connector claim matching is heuristic and partial
3. frontend fallback rendering can fabricate audit-like rows even without true audited provenance

## What the current UI actually reads and renders

Generalized UI path:

- `frontend/src/features/generalized-verification/pages/GeneralizedVerifyPage.jsx`
- `frontend/src/features/generalized-verification/hooks/useGeneralizedVerificationWorkspace.js`
- `frontend/src/features/generalized-verification/utils/viewModels.js`

The hook fetches a large set of endpoints concurrently with `Promise.allSettled`.

### Important reality

The generalized UI does not primarily read the nested `session.extraction`, `session.trust`, and `session.audit` bundle from `/sessions/{id}`. `normalizeSessionOverview` discards most of that nested structure and instead relies on specialized generalized endpoints.

### Audit rendering reality

`AuditDetailCard.jsx` renders evidence details as raw JSON blocks. The UI does not enforce strong provenance semantics. If the backend audit item includes broad or misleading evidence, the UI presents it verbatim.

### Highlight rendering reality

The document highlight viewers use credential bounding boxes, not audit-evidence-specific bounding boxes. This means the visible highlight can imply stronger field-to-evidence binding than the audit evidence really has.

## Precedence And Fallback Rules

## 1. Native Text vs OCR

Actual precedence:

1. native PDF text extraction always runs first
2. OCR is only used when the document or page is judged scanned/text-sparse
3. hybrid mode may mix native text for some pages and OCR for others

## 2. PaddleOCR vs Tesseract

Actual precedence:

1. PaddleOCR first when backend mode is `AUTO` or `PADDLE_PREFERRED`
2. Tesseract fallback if Paddle is unavailable or fails
3. Tesseract-only if configured explicitly
4. no OCR at all in `NATIVE_ONLY`

## 3. Deterministic Extraction vs GLiNER Enrichment

Actual precedence:

1. deterministic extraction is the base path
2. NVIDIA enrichment augments or refines when enabled and configured
3. deterministic output survives if NVIDIA is off/fails

## 4. Generalized Analysis vs Legacy Trust Aliases

These are parallel systems, not one strict stack.

- the legacy verify runtime builds five trust aliases and connector input
- generalized endpoints rebuild richer credentials/plan/audits from extraction/session state

The generalized UI mainly consumes specialized generalized endpoints, while the legacy verify page consumes the nested legacy payloads.

## 5. MiniMax/NVIDIA Reasoning vs Deterministic Fallback

Actual agent precedence:

1. deterministic provider is always available as the baseline
2. NVIDIA provider runs only if enabled/configured
3. on provider failure/unavailability, execution falls back to deterministic

### Important limitation

Agent outputs can only override planning in narrow cases:

- category override only when the existing category is `unknown`
- route override only when the current route is `manual_review` and the suggested provider is available

So agent reasoning is not a general planner override.

## 6. Entra Preferred Route vs Local Mock Execution

Actual precedence:

1. planner may mark Entra as preferred
2. provider runtime selects an executable provider from the registry and operating mode
3. in common repo runtime, that executable provider is `local_mock`

Therefore Entra preference is often descriptive metadata, not execution truth.

## 7. Provider Task Result vs Audit Fallback Logic

Actual precedence is mixed:

- if concrete audit items exist, the UI renders them
- if they do not, `viewModels.js` fabricates fallback audit rows from credentials

This means rendered audit content can exist even when no robust provider-backed audit was persisted.

## Implementation-Reality Gaps

## What The System Claims To Do vs What It Actually Does Today

### Robust document scanning

Claim:

- robust upload validation and scanning

Actual:

- upload path uses the simpler backend PDF validator
- malware scanning depends on external `clamscan`
- without `clamscan`, the system falls back to a SHA256 blocklist check rather than full antivirus scanning

### PII extraction

Claim:

- rich NVIDIA-enabled PII extraction layered onto OCR/native parsing

Actual:

- deterministic extraction is the real primary extractor
- document-family specialization is weak
- GLiNER enrichment is optional and additive
- metadata can imply NVIDIA provenance even when enrichment did not actually succeed
- generic labels such as dates and identifiers are driven by broad regex/keyword rules

### Validation

Claim:

- generalized credentials route through provider-backed verifier infrastructure with Entra-first preference

Actual:

- route metadata may say Entra is preferred
- actual execution is often `local_mock`
- the active legacy verify path still uses a narrow VIT connector plus trust-engine flow
- category-level verifier tasks are often created from weak semantic fragments rather than high-confidence credentials

### Audit evidence

Claim:

- field-level audits backed by real evidence and provider/task outcomes

Actual:

- audit evidence is often broad rather than field-specific
- every card can inherit global connector/trust artifacts
- partial claim matches can mark one field verified even while the overall connector result is mismatch
- frontend fallback logic can fabricate audit-like rows if true audits are absent

### Entra-first verification

Claim:

- Entra is the primary verification rail when possible

Actual:

- Entra preference is commonly only route metadata
- provider mode and registry selection usually drive execution to `local_mock`
- the legacy verification runtime does not use Entra at all

### NVIDIA-enabled reasoning

Claim:

- NVIDIA reasoning materially improves classification/routing

Actual:

- deterministic reasoning remains the baseline
- NVIDIA can only override classification/routing in narrow bounded cases
- fallback to deterministic is normal when NVIDIA is unavailable or disabled

### Local verification store usage

Claim:

- local/mock validation is a temporary compatibility mechanism

Actual:

- in the current compose-style runtime, it is usually the active execution rail
- many visible verification outcomes therefore reflect local fixture matching rather than external-provider truth

## Main Breakpoints

Ranked by downstream impact on pipeline quality.

## 1. Weak semantic field-to-credential transformation

- Symptom: semantically weak fields become full verification tasks.
- Exact code: `backend/app/verification_domain/planner.py`, especially credential/category transformation and `classify_credential_category(...)`.
- Why it happens: category inference is mostly keyword-driven and treats partial fields like `issuer`, `credential_title`, or `person_name` as verification-grade credentials.
- Downstream impact: routing becomes noisy, provider selection becomes semantically weak, local mock matching creates false mismatch/unverified churn, and audit cards inherit bad task semantics.

## 2. Weak OCR/native text to field binding

- Symptom: extracted values have fragile provenance and bounding boxes.
- Exact code: `extraction/parser/document_parser.py`, `extraction/analysis/pipeline.py`, `extraction/grounding/spatial_locator.py`.
- Why it happens: line anchoring is heuristic, page-level hybrid OCR/native mixing can separate semantic selection from strong span provenance, and later audit layers reuse these weak bindings as if they were precise evidence.
- Downstream impact: poor highlights, weak `source_text` fidelity, and misleading audit evidence.

## 3. Generic `date` / identifier overproduction and under-specialization

- Symptom: the system tends to create generic date/id semantics while missing document-specific meaning.
- Exact code: `extraction/analysis/pipeline.py`, `extraction/analysis/nvidia_enrichment.py`.
- Why it happens: label assignment is broad-rule-based, document family specialization is shallow, and regex coverage is incomplete.
- Downstream impact: noisy candidates, poor credential planning inputs, and semantically weak audit cards.

## 4. Audit evidence is not field-scoped enough

- Symptom: audit cards can show `VERIFIED` or `MISMATCH` with evidence that is only loosely related to the rendered field.
- Exact code: `backend/app/verification_domain/adapters.py`, especially `_build_base_evidence(...)`.
- Why it happens: connector responses and overall trust results are attached to every card, and claim-key heuristics can convert partial connector matches into field verification.
- Downstream impact: the UI communicates stronger verification confidence than the actual evidence supports.

## 5. Local mock mismatch noise dominates provider truth

- Symptom: many results are driven by fixture matching rather than authoritative verification.
- Exact code: `backend/app/verifier_providers/providers/local_mock.py`, provider registry/runtime assembly in `backend/app/verifier_providers/service.py` and related files.
- Why it happens: provider operating mode commonly resolves to `LOCAL_MOCK`, and route preference for Entra does not control actual execution.
- Downstream impact: users see mismatch/manual-review/unverified noise that reflects fixture coverage and value normalization quirks more than real-world verification quality.

## 6. Legacy trust flow and generalized flow are not a single coherent pipeline

- Symptom: different endpoints/pages can show different truths for the same session.
- Exact code: `backend/app/workflow/runtime.py`, `backend/app/verification_domain/service.py`, `backend/app/verifier_execution/service.py`, `frontend/src/features/generalized-verification/hooks/useGeneralizedVerificationWorkspace.js`.
- Why it happens: the legacy verify route persists one bundle; generalized endpoints often recompute artifacts on demand; the generalized UI ignores much of the legacy nested payload.
- Downstream impact: users and developers can reason from inconsistent artifacts and think the pipeline is more unified than it is.

## 7. Provenance and status metadata can overstate what really ran

- Symptom: metadata implies NVIDIA/provider-backed enrichment even when fallbacks handled the real work.
- Exact code: `extraction/analysis/nvidia_enrichment.py`, provider/agent status endpoints.
- Why it happens: metadata defaults and transition notes are optimistic/descriptive rather than strict execution provenance.
- Downstream impact: debugging becomes harder because observed outputs look more sophisticated than the executed path actually was.

## Next Fixes In Order

These are the highest-value fixes in dependency order.

## 1. Fix semantic credential construction before touching audit UX

Why first:

- The audit and validation layers are downstream of credential semantics.
- If `issuer`, `name`, and generic fragments keep becoming verification tasks, every later layer will stay noisy.

## 2. Tighten field provenance and field-to-source binding

Why second:

- Once credential semantics improve, the next blocker is whether each field has strong `value`, `source_text`, page, and bbox provenance.
- Audit quality and highlight quality both depend on this.

## 3. Replace broad generic labeling with document-family-aware extraction rules

Why third:

- After provenance is reliable, label quality needs to become more specific.
- This is the point to reduce generic `date` / `identifier` overproduction and improve document-specific meaning.

## 4. Rebuild audit assembly so evidence is field-scoped and provenance-strict

Why fourth:

- Audit should only be fixed after the extraction semantics and provenance feeding it are trustworthy.
- Otherwise the UI will simply present a cleaner version of bad evidence.

## 5. Align provider execution truth with route metadata and surface that clearly

Why fifth:

- Once upstream semantics are clean, users need honest execution truth.
- At that point it becomes worth making Entra-vs-local execution explicit and reducing local-mock noise or isolating it as demo-only behavior.

## Files Inspected

Backend/session/workflow:

- `backend/app/main.py`
- `backend/app/sessions/routes.py`
- `backend/app/sessions/models.py`
- `backend/app/sessions/constants.py`
- `backend/app/workflow/runtime.py`
- `backend/app/workflow/service.py`
- `backend/app/workflow/repository.py`
- `backend/app/workflow/state_machine.py`
- `backend/app/orchestrator/orchestrator.py`
- `backend/app/api/routes.py`
- `backend/app/trust/trust_engine.py`
- `backend/app/audit/service.py`
- `backend/app/audit/receipt_generator.py`
- `backend/app/audit/models.py`
- `backend/app/cleanup/controller.py`

Verification domain / provider execution:

- `backend/app/verification_domain/service.py`
- `backend/app/verification_domain/planner.py`
- `backend/app/verification_domain/adapters.py`
- `backend/app/verification_domain/contracts.py`
- `backend/app/verification_domain/routing.py`
- `backend/app/verifier_execution/service.py`
- `backend/app/verifier_execution/adapters.py`
- `backend/app/verifier_execution/contracts.py`
- `backend/app/verifier_execution/executor.py`
- `backend/app/verifier_execution/registry.py`
- `backend/app/verifier_execution/verifiers/base.py`
- `backend/app/verifier_execution/verifiers/manual_review.py`
- `backend/app/verifier_execution/verifiers/identity_db.py`
- `backend/app/verifier_execution/verifiers/address_check.py`
- `backend/app/verifier_execution/verifiers/passport_db.py`
- `backend/app/verifier_execution/verifiers/license_registry.py`
- `backend/app/verifier_execution/verifiers/academic_registry.py`
- `backend/app/verifier_execution/verifiers/certificate_registry.py`
- `backend/app/verifier_execution/verifiers/financial_registry.py`
- `backend/app/verifier_execution/verifiers/tax_authority.py`
- `backend/app/verifier_providers/service.py`
- `backend/app/verifier_providers/registry.py`
- `backend/app/verifier_providers/policies.py`
- `backend/app/verifier_providers/contracts.py`
- `backend/app/verifier_providers/base.py`
- `backend/app/verifier_providers/providers/local_mock.py`
- `backend/app/verifier_providers/providers/entra_verified_id.py`
- `backend/app/verifier_providers/providers/identity_http.py`
- `backend/app/verifier_providers/providers/academic_registry_http.py`
- `backend/app/verifier_providers/providers/generic_http_json.py`
- `backend/app/verifier_providers/fixtures/local_verification_records.json`

Connectors / inference / agent orchestration:

- `backend/app/connectors/broker.py`
- `backend/app/connectors/vit_mock.py`
- `backend/app/connectors/schema.py`
- `backend/app/connectors/entra_verified_id_mock.py`
- `backend/app/connectors/fixtures/vit_registry.json`
- `backend/app/inference/nvidia.py`
- `backend/app/agent_orchestration/service.py`
- `backend/app/agent_orchestration/contracts.py`
- `backend/app/agent_orchestration/adapters.py`
- `backend/app/agent_orchestration/graph.py`
- `backend/app/agent_orchestration/policies.py`
- `backend/app/agent_orchestration/providers/deterministic.py`
- `backend/app/agent_orchestration/providers/nvidia.py`

Extraction:

- `extraction/parser/document_parser.py`
- `extraction/analysis/pipeline.py`
- `extraction/analysis/nvidia_enrichment.py`
- `extraction/ocr/engine.py`
- `extraction/schema/models.py`
- `extraction/grounding/spatial_locator.py`
- `extraction/security/validator.py`
- `backend/app/security/pdf_validator.py`

Frontend:

- `frontend/src/App.jsx`
- `frontend/src/lib/api.js`
- `frontend/src/routes/paths.js`
- `frontend/src/pages/UploadPage.jsx`
- `frontend/src/pages/VerifyPage.jsx`
- `frontend/src/trust_panel/TrustPanel.jsx`
- `frontend/src/audit_receipt/AuditReceiptPanel.jsx`
- `frontend/src/pdf_viewer/PdfViewer.jsx`
- `frontend/src/pdf_viewer/HighlightOverlay.jsx`
- `frontend/src/features/generalized-verification/api/generalizedVerificationApi.js`
- `frontend/src/features/generalized-verification/hooks/useGeneralizedVerificationWorkspace.js`
- `frontend/src/features/generalized-verification/types/contracts.js`
- `frontend/src/features/generalized-verification/utils/normalizers.js`
- `frontend/src/features/generalized-verification/utils/viewModels.js`
- `frontend/src/features/generalized-verification/pages/GeneralizedVerifyPage.jsx`
- `frontend/src/features/generalized-verification/components/AnalysisTab.jsx`
- `frontend/src/features/generalized-verification/components/AuditTab.jsx`
- `frontend/src/features/generalized-verification/components/AuditDetailCard.jsx`
- `frontend/src/features/generalized-verification/components/DocumentTab.jsx`
- `frontend/src/features/generalized-verification/components/DocumentHighlightViewer.jsx`
- `frontend/src/features/generalized-verification/components/HighlightOverlay.jsx`
- `frontend/src/features/generalized-verification/components/WorkspaceLeftSidebar.jsx`
- `frontend/src/features/generalized-verification/components/WorkspaceRightSidebar.jsx`

Repo claims / config references checked against code:

- `docker-compose.yml`
- `README.md`
- `docs/live_provider_transition.md`
- `docs/generalized_verification_contracts.md`
