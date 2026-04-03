import assert from "node:assert/strict";
import {
  normalizeCredentialBundles,
  normalizeCredentialCollection,
  normalizeDocumentProfile,
  normalizeVerificationPlan,
  normalizeVerificationTaskResults,
} from "../src/features/generalized-verification/utils/normalizers.js";
import {
  buildAuditDetailViewModels,
  buildHighlightItems,
  buildStatusCounts,
  buildTaskExecutionSummary,
  buildWorkspaceViewModel,
} from "../src/features/generalized-verification/utils/viewModels.js";
import {
  createEmptyAnalysisStatus,
  createEmptyCredentialBundleCollection,
  createEmptyCredentialAuditCollection,
  createEmptyCredentialCollection,
  createEmptyDocumentProfile,
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
        documentProfile: createEmptyDocumentProfile("session-1"),
        credentials: createEmptyCredentialCollection("session-1"),
        verificationPlan: createEmptyVerificationPlan("session-1"),
        verificationTaskResults: createEmptyVerificationTaskResultCollection("session-1"),
        credentialBundles: createEmptyCredentialBundleCollection("session-1"),
        credentialAudits: createEmptyCredentialAuditCollection("session-1"),
        verificationSummary: createEmptyVerificationSummary("session-1"),
        analysisStatus: createEmptyAnalysisStatus("session-1"),
        executionStatus: createEmptyVerificationExecutionStatus("session-1"),
      });

      const counts = buildStatusCounts(viewModel.auditDetails);

      assert.equal(viewModel.flags.hasCredentials, false);
      assert.match(viewModel.messages.document, /No PDF/i);
      assert.match(viewModel.messages.credentials, /No credentials/i);
      assert.equal(counts.UNVERIFIED, 0);
      assert.equal(viewModel.taskExecutionSummary.totalTasks, 0);
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
];
