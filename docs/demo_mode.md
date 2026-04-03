# Demo Mode

## Purpose

Stage 8 introduces an explicit demo-mode transition layer so the platform can be presented reliably before a live Microsoft Entra Verified ID tenant is available.

Demo mode is intentional and honest:

- it uses seeded, deterministic provider responses
- it keeps Microsoft Entra Verified ID as the primary trust rail in architecture and routing
- it does not claim that live provider execution happened
- it preserves the same verifier registry, provider registry, and task execution contracts that live mode will use later

## Provider Operating Modes

The provider layer now resolves one bounded operating mode:

- `DEMO_MOCK`: seeded Entra-aligned or supplementary provider responses are generated locally for presentation
- `LOCAL_MOCK`: only the bounded local mock provider path is active
- `EXTERNAL_CONFIGURED`: live outbound provider execution is allowed behind policy and allowlists
- `LIVE_DISABLED`: live providers are not enabled; local fallback/manual review remains available
- `MANUAL_ONLY`: executable provider paths are disabled and credentials should fall back to manual review

## How To Enable Demo Mode

Set environment variables before running the backend:

```powershell
$env:VERIFIER_PROVIDER_OPERATING_MODE="DEMO_MOCK"
$env:VERIFIER_DEMO_PROFILE_KEY="academic_transcript_demo"
```

Optional supporting values:

```powershell
$env:VERIFIER_EXECUTION_ENVIRONMENT_LABEL="POC demo environment"
$env:VERIFIER_ENABLED_PROVIDERS="entra_verified_id,identity_http,academic_registry_http,local_mock"
```

If `VERIFIER_PROVIDER_OPERATING_MODE` is not set, the repo stays in a safer non-demo mode by default.

## Seeded Demo Profiles

Current seeded profiles:

- `academic_transcript_demo`
- `certificate_partial_demo`
- `identity_mismatch_demo`
- `mixed_manual_review_demo`

These profiles produce deterministic, explainable provider outputs such as:

- verified
- partial
- mismatch
- manual review

## What Is Mocked

- Microsoft Entra Verified ID provider responses when `DEMO_MOCK` is active
- supplementary HTTP-provider responses when `DEMO_MOCK` is active
- provider execution traces still persist only redacted summaries and technical metadata

## What Is Not Mocked

- top-level workflow state machine
- deterministic trust engine
- generalized artifact generation
- verifier registry and per-credential task execution flow
- cleanup and session boundaries

## Reviewer Visibility

The generalized workspace now shows:

- provider operating mode
- active demo profile when seeded demo mode is active
- whether Microsoft Entra Verified ID was selected in demo mode or live-configured mode
- whether a fallback or manual-review path was used

## Demo Notes

- Demo mode should never be labeled as live provider execution.
- Seeded provider results are normalized through the same provider contracts used by live mode.
- If no safe executable path exists, manual review remains the honest fallback.
