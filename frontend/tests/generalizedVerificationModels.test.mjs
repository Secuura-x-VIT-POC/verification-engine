import assert from "node:assert/strict";
import {
  normalizeAgentCredentialCandidates,
  normalizeAgentDocumentUnderstanding,
  normalizeAgentRouteRecommendations,
  normalizeAgentRunStatus,
  normalizeCredentialBundles,
  normalizeCredentialCollection,
  normalizeDocumentProfile,
  normalizeProviderCapabilities,
  normalizeProviderExecutionStatus,
  normalizeProviderExecutionTraces,
  normalizeVerificationPlan,
  normalizeVerificationTaskResults,
} from "../src/features/generalized-verification/utils/normalizers.js";
import {
  buildAuditDetailViewModels,
  buildHighlightItems,
  buildProviderExecutionSummary,
  buildStatusCounts,
  buildTaskExecutionSummary,
  buildWorkspaceViewModel,
} from "../src/features/generalized-verification/utils/viewModels.js";
import {
  createEmptyAgentCredentialCandidateCollection,
  createEmptyAgentDocumentUnderstanding,
  createEmptyAgentRouteRecommendationCollection,
  createEmptyAgentRunStatus,
  createEmptyAnalysisStatus,
  createEmptyCredentialBundleCollection,
  createEmptyCredentialAuditCollection,
  createEmptyCredentialCollection,
  createEmptyDocumentProfile,
  createEmptyProviderCapabilityCollection,
  createEmptyProviderExecutionStatus,
  createEmptyProviderExecutionTraceCollection,
  createEmptyVerificationExecutionStatus,
  createEmptySessionOverview,
  createEmptyVerificationPlan,
  createEmptyVerificationTaskResultCollection,
  createEmptyVerificationSummary,
} from "../src/features/generalized-verification/types/contracts.js";

export const checks = [
  {
    name: "normalizeDocumentProfile returns safe defaults for null payloads",
    run() {
      const profile = normalizeDocumentProfile(null, "session-1");

      assert.equal(profile.session_id, "session-1");
      assert.equal(profile.document_type, "unknown");
      assert.equal(profile.document_family, "unknown");
      assert.deepEqual(profile.detected_categories, []);
    },
  },
  {
    name: "normalizeCredentialCollection preserves valid geometry and drops missing box values",
    run() {
      const credentials = normalizeCredentialCollection(
        {
          session_id: "session-1",
          credentials: [
            {
              credential_id: "name",
              label: "Candidate name",
              category: "identity",
              value: "Alex Morgan",
              requires_verification: true,
              bounding_box: { page: 1, x0: 40, y0: 80, x1: 220, y1: 120 },
            },
            {
              credential_id: "id",
              label: "Document ID",
              category: "identity",
              value: "ID-44",
              requires_verification: true,
              bounding_box: {},
            },
          ],
        },
        "session-1"
      );

      assert.equal(credentials.credentials[0].bounding_box.page, 1);
      assert.equal(credentials.credentials[1].bounding_box, null);
    },
  },
  {
    name: "buildHighlightItems uses audit status colors and skips credentials without geometry",
    run() {
      const credentials = normalizeCredentialCollection(
        {
          session_id: "session-1",
          credentials: [
            {
              credential_id: "passport",
              label: "Passport number",
              category: "passport",
              value: "P1234",
              requires_verification: true,
              bounding_box: { page: 1, x0: 60, y0: 120, x1: 220, y1: 155 },
            },
            {
              credential_id: "address",
              label: "Address",
              category: "address",
              value: "No geometry",
              requires_verification: true,
            },
          ],
        },
        "session-1"
      );
      const plan = normalizeVerificationPlan(
        {
          session_id: "session-1",
          route_decisions: [
            {
              credential_id: "passport",
              selected_verifier_key: "passport_db",
              selected_verifier_label: "Passport DB",
              route_reason: "Passport category mapped to registry",
              preferred_provider_key: null,
              preferred_provider_label: null,
              planned_provider_key: null,
              planned_provider_label: null,
              fallback_verifiers: [],
              manual_review_recommended: false,
            },
          ],
          tasks: [],
        },
        "session-1"
      );
      const audits = {
        session_id: "session-1",
        document_type: "passport",
        audits: [
          {
            credential_id: "passport",
            label: "Passport number",
            document_value: "P1234",
            normalized_value: "P1234",
            verifier_label: "Passport DB",
            audit_status: "VERIFIED",
            outcome_color: "green",
            explanation: "Matched with registry.",
            reason_codes: ["REGISTRY_MATCH"],
            matched_fields: { passport_number: "P1234" },
            mismatched_fields: {},
            missing_fields: [],
            evidence: [],
            timestamp: null,
          },
        ],
      };

      const highlights = buildHighlightItems(credentials, audits, plan);

      assert.equal(highlights.length, 1);
      assert.equal(highlights[0].credentialId, "passport");
      assert.equal(highlights[0].outcomeColor, "green");
      assert.equal(highlights[0].auditStatus, "VERIFIED");
      assert.ok(highlights[0].relativeBox.width > 0);
    },
  },
  {
    name: "buildAuditDetailViewModels falls back safely when audit evidence is missing",
    run() {
      const credentials = normalizeCredentialCollection(
        {
          session_id: "session-1",
          credentials: [
            {
              credential_id: "certificate",
              label: "Certificate",
              category: "certificate",
              value: "Issued",
              requires_verification: false,
            },
            {
              credential_id: "tax-id",
              label: "Tax ID",
              category: "tax",
              value: "T-99",
              requires_verification: true,
            },
          ],
        },
        "session-1"
      );

      const details = buildAuditDetailViewModels(
        credentials,
        createEmptyCredentialAuditCollection("session-1"),
        createEmptyVerificationPlan("session-1")
      );

      assert.equal(details[0].auditStatus, "NOT_APPLICABLE");
      assert.equal(details[1].auditStatus, "UNVERIFIED");
      assert.match(details[1].explanation, /Audit not yet available/i);
    },
  },
  {
    name: "buildWorkspaceViewModel reports stable empty states and counts",
    run() {
      const viewModel = buildWorkspaceViewModel({
        session: createEmptySessionOverview("session-1"),
        agentDocumentUnderstanding: createEmptyAgentDocumentUnderstanding("session-1"),
        agentCredentialCandidates: createEmptyAgentCredentialCandidateCollection("session-1"),
        agentRouteRecommendations: createEmptyAgentRouteRecommendationCollection("session-1"),
        agentRunStatus: createEmptyAgentRunStatus("session-1"),
        documentProfile: createEmptyDocumentProfile("session-1"),
        credentials: createEmptyCredentialCollection("session-1"),
        verificationPlan: createEmptyVerificationPlan("session-1"),
        verificationTaskResults: createEmptyVerificationTaskResultCollection("session-1"),
        credentialBundles: createEmptyCredentialBundleCollection("session-1"),
        credentialAudits: createEmptyCredentialAuditCollection("session-1"),
        verificationSummary: createEmptyVerificationSummary("session-1"),
        analysisStatus: createEmptyAnalysisStatus("session-1"),
        executionStatus: createEmptyVerificationExecutionStatus("session-1"),
        providerExecutionTraces: createEmptyProviderExecutionTraceCollection("session-1"),
        providerExecutionStatus: createEmptyProviderExecutionStatus("session-1"),
        providerCapabilities: createEmptyProviderCapabilityCollection("session-1"),
      });

      const counts = buildStatusCounts(viewModel.auditDetails);

      assert.equal(viewModel.flags.hasCredentials, false);
      assert.match(viewModel.messages.document, /No PDF/i);
      assert.match(viewModel.messages.credentials, /No credentials/i);
      assert.equal(counts.UNVERIFIED, 0);
      assert.equal(viewModel.taskExecutionSummary.totalTasks, 0);
      assert.equal(viewModel.agentUnderstandingSummary.documentTypeGuess, "unknown");
    },
  },
  {
    name: "execution payload normalization and summary stay stable",
    run() {
      const taskResults = normalizeVerificationTaskResults(
        {
          session_id: "session-1",
          results: [
            {
              task_id: "task-1",
              credential_id: "name-1",
              verifier_key: "identity_db",
              verifier_label: "Identity Database",
              task_status: "SUCCEEDED",
              audit_status: "VERIFIED",
              outcome_color: "green",
              explanation: "Matched.",
              reason_codes: ["REGISTRY_MATCH"],
              matched_fields: { name: "Kanak Sharma" },
              raw_result_summary: { execution_mode: "connector_match" },
              confidence: 0.98,
              executed_at: "2026-04-03T00:00:00",
              latency_ms: 12,
              manual_review_recommended: false,
            },
          ],
        },
        "session-1"
      );
      const bundles = normalizeCredentialBundles(
        {
          session_id: "session-1",
          bundles: [
            {
              credential_id: "name-1",
              label: "Candidate Name",
              category: "identity",
              selected_task_ids: ["task-1"],
              result_count: 1,
              final_audit_status: "VERIFIED",
              final_outcome_color: "green",
              explanation: "Matched.",
              reason_codes: ["REGISTRY_MATCH"],
              best_result: taskResults.results[0],
              all_results: taskResults.results,
            },
          ],
        },
        "session-1"
      );
      const summary = buildTaskExecutionSummary(taskResults, {
        verification_execution_status: "READY",
      });
      const details = buildAuditDetailViewModels(
        normalizeCredentialCollection(
          {
            session_id: "session-1",
            credentials: [
              {
                credential_id: "name-1",
                label: "Candidate Name",
                category: "identity",
                value: "Kanak Sharma",
                normalized_value: "Kanak Sharma",
                requires_verification: true,
              },
            ],
          },
          "session-1"
        ),
        createEmptyCredentialAuditCollection("session-1"),
        createEmptyVerificationPlan("session-1"),
        bundles
      );

      assert.equal(summary.totalTasks, 1);
      assert.equal(summary.counts.SUCCEEDED, 1);
      assert.equal(details[0].execution.status, "SUCCEEDED");
      assert.equal(details[0].auditStatus, "VERIFIED");
    },
  },
  {
    name: "agent payload normalization and workspace mapping stay stable",
    run() {
      const understanding = normalizeAgentDocumentUnderstanding(
        {
          session_id: "session-1",
          document_type_guess: "utility_document",
          document_family_guess: "address_document",
          confidence: 0.81,
          detected_sections: ["identity_section"],
          detected_entities: [{ label: "Residency Proof Number", category: "address", credential_id: "residency-1" }],
          pii_signals: ["Residency Proof Number"],
          credential_candidates: ["candidate-residency-1"],
          reasoning_summary: "Agent-assisted understanding recognized an address-like proof identifier.",
          manual_review_recommended: true,
        },
        "session-1"
      );
      const candidates = normalizeAgentCredentialCandidates(
        {
          session_id: "session-1",
          candidates: [
            {
              candidate_id: "candidate-residency-1",
              label: "Residency Proof Number",
              category: "address",
              source_fields: ["Residency Proof Number"],
              grouped_field_ids: ["residency-1"],
              grouped_values: { "Residency Proof Number": "ADDR-42" },
              confidence: 0.88,
              verification_recommended: true,
              verification_reason: "Address-like proof identifiers should be verified.",
              possible_verifier_keys: ["address_check"],
              ambiguity_flags: [],
            },
          ],
        },
        "session-1"
      );
      const routes = normalizeAgentRouteRecommendations(
        {
          session_id: "session-1",
          recommendations: [
            {
              candidate_id: "candidate-residency-1",
              recommended_verifier_key: "address_check",
              alternative_verifier_keys: ["manual_review"],
              route_reason: "Agent-assisted grouping suggests an address verifier.",
              confidence: 0.88,
              manual_review_recommended: true,
            },
          ],
        },
        "session-1"
      );
      const agentRunStatus = normalizeAgentRunStatus(
        {
          session_id: "session-1",
          agent_run_status: "READY",
          provider_used: "deterministic",
          fallback_used: false,
          warnings: [],
        },
        "session-1"
      );

      const viewModel = buildWorkspaceViewModel({
        session: createEmptySessionOverview("session-1"),
        agentDocumentUnderstanding: understanding,
        agentCredentialCandidates: candidates,
        agentRouteRecommendations: routes,
        agentRunStatus,
        documentProfile: createEmptyDocumentProfile("session-1"),
        credentials: normalizeCredentialCollection(
          {
            session_id: "session-1",
            credentials: [
              {
                credential_id: "residency-1",
                label: "Residency Proof Number",
                category: "address",
                value: "ADDR-42",
                requires_verification: true,
                bounding_box: { page: 1, x0: 10, y0: 10, x1: 120, y1: 20 },
              },
            ],
          },
          "session-1"
        ),
        verificationPlan: normalizeVerificationPlan(
          {
            session_id: "session-1",
            route_decisions: [
            {
              credential_id: "residency-1",
              selected_verifier_key: "address_check",
              selected_verifier_label: "Address Check",
              route_reason: "Baseline route",
              preferred_provider_key: null,
              preferred_provider_label: null,
              planned_provider_key: "local_mock",
              planned_provider_label: "Local Mock Provider",
              fallback_verifiers: [],
              manual_review_recommended: false,
            },
            ],
            tasks: [],
          },
          "session-1"
        ),
        verificationTaskResults: createEmptyVerificationTaskResultCollection("session-1"),
        credentialBundles: createEmptyCredentialBundleCollection("session-1"),
        credentialAudits: createEmptyCredentialAuditCollection("session-1"),
        verificationSummary: createEmptyVerificationSummary("session-1"),
        analysisStatus: createEmptyAnalysisStatus("session-1"),
        executionStatus: createEmptyVerificationExecutionStatus("session-1"),
        providerExecutionTraces: createEmptyProviderExecutionTraceCollection("session-1"),
        providerExecutionStatus: createEmptyProviderExecutionStatus("session-1"),
        providerCapabilities: createEmptyProviderCapabilityCollection("session-1"),
      });

      assert.equal(viewModel.agentUnderstandingSummary.documentTypeGuess, "utility_document");
      assert.equal(viewModel.analysisRows[0].agentRecommendedVerifierLabel, "Address Check");
      assert.equal(viewModel.auditDetails[0].agentAssisted, true);
      assert.equal(viewModel.agentStatusLabel, "Ready");
    },
  },
  {
    name: "provider payload normalization and summary stay bounded",
    run() {
      const traces = normalizeProviderExecutionTraces(
        {
          session_id: "session-1",
          traces: [
            {
              request_id: "trace-1",
              provider_key: "identity_http",
              verifier_key: "identity_db",
              technical_status: "SUCCESS",
              outbound_mode: "HTTP_JSON",
              retry_count: 1,
              response_summary: { source: "fixture" },
              fallback_used: false,
            },
          ],
        },
        "session-1"
      );
      const status = normalizeProviderExecutionStatus(
        {
          session_id: "session-1",
          provider_execution_status: "READY",
          trace_count: 1,
          provider_keys_used: ["identity_http"],
          outbound_attempted: true,
          fallback_used: false,
        },
        "session-1"
      );
      const capabilities = normalizeProviderCapabilities(
        {
          session_id: "session-1",
          capabilities: [
            {
              provider_key: "identity_http",
              provider_label: "Supplementary Identity HTTP Provider",
              supported_verifier_keys: ["identity_db"],
              supported_categories: ["identity"],
              enabled: true,
            },
          ],
        },
        "session-1"
      );

      const summary = buildProviderExecutionSummary(traces, status, capabilities);

      assert.equal(summary.traceCount, 1);
      assert.equal(summary.overallLabel, "Ready");
      assert.equal(summary.providerKeysUsed[0], "identity_http");
      assert.equal(summary.enabledProviders[0], "Supplementary Identity HTTP Provider");
    },
  },
  {
    name: "workspace view model labels Entra-first and fallback routes honestly",
    run() {
      const viewModel = buildWorkspaceViewModel({
        session: createEmptySessionOverview("session-1"),
        agentDocumentUnderstanding: createEmptyAgentDocumentUnderstanding("session-1"),
        agentCredentialCandidates: createEmptyAgentCredentialCandidateCollection("session-1"),
        agentRouteRecommendations: createEmptyAgentRouteRecommendationCollection("session-1"),
        agentRunStatus: createEmptyAgentRunStatus("session-1"),
        documentProfile: createEmptyDocumentProfile("session-1"),
        credentials: normalizeCredentialCollection(
          {
            session_id: "session-1",
            credentials: [
              {
                credential_id: "name-1",
                label: "Candidate Name",
                category: "identity",
                value: "Kanak Sharma",
                requires_verification: true,
              },
            ],
          },
          "session-1"
        ),
        verificationPlan: normalizeVerificationPlan(
          {
            session_id: "session-1",
            route_decisions: [
              {
                credential_id: "name-1",
                selected_verifier_key: "identity_db",
                selected_verifier_label: "Identity Database",
                route_reason: "Identity credential.",
                preferred_provider_key: "entra_verified_id",
                preferred_provider_label: "Microsoft Entra Verified ID",
                planned_provider_key: "local_mock",
                planned_provider_label: "Local Mock Provider",
                fallback_verifiers: ["manual_review"],
                manual_review_recommended: false,
              },
            ],
            tasks: [
              {
                task_id: "task-1",
                credential_id: "name-1",
                verifier_key: "identity_db",
                verifier_label: "Identity Database",
                verification_type: "identity",
                required: true,
                status: "PLANNED",
                reason_codes: ["ENTRA_PREFERRED_ROUTE", "LOCAL_PROVIDER_FALLBACK"],
                input_payload: {
                  preferred_provider_key: "entra_verified_id",
                  preferred_provider_label: "Microsoft Entra Verified ID",
                  planned_provider_key: "local_mock",
                  planned_provider_label: "Local Mock Provider",
                },
              },
            ],
          },
          "session-1"
        ),
        verificationTaskResults: createEmptyVerificationTaskResultCollection("session-1"),
        credentialBundles: createEmptyCredentialBundleCollection("session-1"),
        credentialAudits: createEmptyCredentialAuditCollection("session-1"),
        verificationSummary: createEmptyVerificationSummary("session-1"),
        analysisStatus: createEmptyAnalysisStatus("session-1"),
        executionStatus: createEmptyVerificationExecutionStatus("session-1"),
        providerExecutionTraces: createEmptyProviderExecutionTraceCollection("session-1"),
        providerExecutionStatus: createEmptyProviderExecutionStatus("session-1"),
        providerCapabilities: normalizeProviderCapabilities(
          {
            session_id: "session-1",
            capabilities: [
              {
                provider_key: "local_mock",
                provider_label: "Local Mock Provider",
                supported_verifier_keys: ["identity_db"],
                supported_categories: ["identity"],
                enabled: true,
              },
            ],
          },
          "session-1"
        ),
      });

      assert.equal(viewModel.analysisRows[0].routeDispositionLabel, "Entra unavailable");
      assert.equal(viewModel.analysisRows[0].preferredProviderLabel, "Microsoft Entra Verified ID");
      assert.match(viewModel.messages.provider, /preferred VC trust rail/i);
      assert.equal(viewModel.providerExecutionSummary.primaryTrustRailEnabled, false);
    },
  },
];
