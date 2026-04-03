# Demo Pack

This demo pack supports consistent presentations of the generalized verification platform without requiring a live Microsoft Entra Verified ID tenant.

## Included Assets

- `scenarios.json`: seeded scenario definitions and presenter-facing descriptions

## Recommended Demo Flow

1. Run the backend in `DEMO_MOCK` mode.
2. Pick one seeded profile such as `academic_transcript_demo`.
3. Upload a compatible sample PDF from your own presentation set or use an existing document that exercises the same categories.
4. Open the generalized workspace and call out:
   - Microsoft Entra Verified ID as the primary trust rail
   - seeded demo-mode execution
   - bounded supplementary/manual-review fallbacks
   - deterministic final trust rendering

## Important

- The demo pack does not label seeded outputs as live results.
- The same verifier and provider contracts are used by both demo and live modes.
