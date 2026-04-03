# Live Provider Transition

## Goal

The Stage 8 provider-mode system is designed so the platform can move from seeded demo behavior to real Microsoft Entra Verified ID and supplementary provider integrations with minimal refactoring.

## Microsoft Entra Verified ID Later

To enable a real Entra path later, the expected work is:

1. Set live provider mode and enable the provider.
2. Provide tenant-specific base URL and credentials.
3. Configure claim mapping and presentation-definition logic for the credential classes you want to support.
4. Validate outbound allowlists, timeouts, retry budgets, and redaction policy in the target environment.

Example environment shape:

```powershell
$env:VERIFIER_PROVIDER_OPERATING_MODE="EXTERNAL_CONFIGURED"
$env:VERIFIER_EXTERNAL_PROVIDER_ENABLED="1"
$env:VERIFIER_ENABLED_PROVIDERS="entra_verified_id,identity_http,academic_registry_http,local_mock"
$env:VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_ENABLED="1"
$env:VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_BASE_URL="https://<tenant-specific-url>"
$env:VERIFIER_PROVIDER_ENTRA_VERIFIED_ID_API_KEY="<credential>"
```

## Supplementary Provider Onboarding Later

Supplementary providers should follow the same pattern:

- create or update a provider adapter under `backend/app/verifier_providers/providers/`
- keep external request/response mapping inside the provider adapter
- normalize everything into `ProviderResponse`
- do not leak vendor-specific logic into verifier execution or trust evaluation

## Before Turning On Live Mode

Validate these areas first:

- outbound domain allowlists
- provider timeout and retry budgets
- payload minimization and redaction
- technical trace persistence does not retain sensitive raw payloads
- route selection only targets executable providers
- demo-mode wording is not shown in live mode
- generalized workspace clearly labels live-configured versus fallback/manual-review results

## Boundaries That Stay The Same

Even after live enablement:

- deterministic verifier execution remains the execution authority
- deterministic trust remains the final document-level authority
- LangGraph remains an enrichment layer, not a trust engine replacement
- Microsoft Entra Verified ID stays the primary VC trust rail for Entra-aligned credential classes
- manual review remains the honest fallback when evidence is insufficient
