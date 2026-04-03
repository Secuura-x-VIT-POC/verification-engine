import {
  createEmptyAnalysisStatus,
  createEmptyCredentialAuditCollection,
  createEmptyCredentialBundleCollection,
  createEmptyCredentialCollection,
  createEmptyDocumentProfile,
  createEmptyVerificationExecutionStatus,
  createEmptySessionOverview,
  createEmptyVerificationPlan,
  createEmptyVerificationTaskResultCollection,
  createEmptyVerificationSummary,
} from "../types/contracts.js";

function asString(value, fallback = "") {
  if (value === null || value === undefined) {
    return fallback;
  }
  return String(value);
}

function asNullableString(value) {
  const normalized = asString(value, "").trim();
  return normalized ? normalized : null;
}

function asBoolean(value, fallback = false) {
  if (typeof value === "boolean") {
    return value;
  }
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return fallback;
}

function asNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const normalized = Number(value);
  return Number.isFinite(normalized) ? normalized : null;
}

function asInteger(value) {
  const normalized = asNumber(value);
  if (normalized === null) {
    return null;
  }
  return Math.trunc(normalized);
}

function asStringArray(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asString(item, "").trim())
    .filter(Boolean);
}

function asObject(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value;
  }
  return {};
}

export function normalizeBoundingBox(payload, fallbackPage = null) {
  const box = asObject(payload);
  const page = asInteger(box.page) ?? fallbackPage;
  const normalized = {
    page,
    x0: asNumber(box.x0),
    y0: asNumber(box.y0),
    x1: asNumber(box.x1),
    y1: asNumber(box.y1),
  };

  if ([normalized.x0, normalized.y0, normalized.x1, normalized.y1].every((value) => value === null)) {
    return null;
  }

  return normalized;
}

export function normalizeDocumentProfile(payload, sessionId = "") {
  const profile = { ...createEmptyDocumentProfile(sessionId), ...asObject(payload) };
  return {
    session_id: asString(profile.session_id, sessionId),
    document_type: asString(profile.document_type, "unknown"),
    document_family: asString(profile.document_family, "unknown"),
    page_count: asInteger(profile.page_count),
    extraction_methods_used: asStringArray(profile.extraction_methods_used),
    pii_detected: asBoolean(profile.pii_detected),
    detected_categories: asStringArray(profile.detected_categories),
    requires_manual_review: asBoolean(profile.requires_manual_review),
    notes: asStringArray(profile.notes),
  };
}

export function normalizeCredentialCollection(payload, sessionId = "") {
  const collection = { ...createEmptyCredentialCollection(sessionId), ...asObject(payload) };
  const credentials = Array.isArray(collection.credentials) ? collection.credentials : [];

  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    credentials: credentials.map((credential, index) => {
      const normalizedCredential = asObject(credential);
      const page = asInteger(normalizedCredential.page);
      return {
        credential_id: asString(normalizedCredential.credential_id, `credential-${index + 1}`),
        label: asString(normalizedCredential.label, `Credential ${index + 1}`),
        category: asString(normalizedCredential.category, "unknown"),
        value: normalizedCredential.value ?? null,
        normalized_value: asNullableString(normalizedCredential.normalized_value),
        source_text: asNullableString(normalizedCredential.source_text),
        confidence: asNumber(normalizedCredential.confidence),
        page,
        bounding_box: normalizeBoundingBox(normalizedCredential.bounding_box, page),
        is_pii: asBoolean(normalizedCredential.is_pii),
        requires_verification: asBoolean(normalizedCredential.requires_verification),
        verification_reason: asNullableString(normalizedCredential.verification_reason),
        extraction_method: asString(normalizedCredential.extraction_method, "unknown"),
      };
    }),
  };
}

export function normalizeVerificationPlan(payload, sessionId = "") {
  const plan = { ...createEmptyVerificationPlan(sessionId), ...asObject(payload) };
  const routeDecisions = Array.isArray(plan.route_decisions) ? plan.route_decisions : [];
  const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];

  return {
    session_id: asString(plan.session_id, sessionId),
    document_type: asString(plan.document_type, "unknown"),
    route_decisions: routeDecisions.map((decision, index) => {
      const normalizedDecision = asObject(decision);
      return {
        credential_id: asString(normalizedDecision.credential_id, `credential-${index + 1}`),
        selected_verifier_key: asString(normalizedDecision.selected_verifier_key, "manual_review"),
        selected_verifier_label: asString(normalizedDecision.selected_verifier_label, "Manual review"),
        route_reason: asString(normalizedDecision.route_reason, "No route reason available."),
        fallback_verifiers: asStringArray(normalizedDecision.fallback_verifiers),
        manual_review_recommended: asBoolean(normalizedDecision.manual_review_recommended),
      };
    }),
    tasks: tasks.map((task, index) => {
      const normalizedTask = asObject(task);
      return {
        task_id: asString(normalizedTask.task_id, `task-${index + 1}`),
        credential_id: asString(normalizedTask.credential_id, `credential-${index + 1}`),
        verifier_key: asString(normalizedTask.verifier_key, "manual_review"),
        verifier_label: asString(normalizedTask.verifier_label, "Manual review"),
        verification_type: asString(normalizedTask.verification_type, "document_review"),
        required: asBoolean(normalizedTask.required),
        status: asString(normalizedTask.status, "PENDING"),
        reason_codes: asStringArray(normalizedTask.reason_codes),
        input_payload: asObject(normalizedTask.input_payload),
      };
    }),
  };
}

export function normalizeCredentialAudits(payload, sessionId = "") {
  const collection = { ...createEmptyCredentialAuditCollection(sessionId), ...asObject(payload) };
  const audits = Array.isArray(collection.audits) ? collection.audits : [];

  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    audits: audits.map((audit, index) => {
      const normalizedAudit = asObject(audit);
      const evidence = Array.isArray(normalizedAudit.evidence) ? normalizedAudit.evidence : [];

      return {
        credential_id: asString(normalizedAudit.credential_id, `credential-${index + 1}`),
        label: asString(normalizedAudit.label, `Credential ${index + 1}`),
        document_value: normalizedAudit.document_value ?? null,
        normalized_value: asNullableString(normalizedAudit.normalized_value),
        verifier_label: asString(normalizedAudit.verifier_label, "Verifier unavailable"),
        audit_status: asString(normalizedAudit.audit_status, "UNVERIFIED"),
        outcome_color: asString(normalizedAudit.outcome_color, "amber"),
        explanation: asString(normalizedAudit.explanation, "No audit explanation is available yet."),
        reason_codes: asStringArray(normalizedAudit.reason_codes),
        matched_fields: asObject(normalizedAudit.matched_fields),
        mismatched_fields: asObject(normalizedAudit.mismatched_fields),
        missing_fields: asStringArray(normalizedAudit.missing_fields),
        evidence: evidence.map((item) => {
          const normalizedItem = asObject(item);
          return {
            evidence_type: asString(normalizedItem.evidence_type, "unknown"),
            source: asString(normalizedItem.source, "unknown"),
            detail: asObject(normalizedItem.detail),
          };
        }),
        timestamp: asNullableString(normalizedAudit.timestamp),
      };
    }),
  };
}

export function normalizeVerificationSummary(payload, sessionId = "") {
  const summary = { ...createEmptyVerificationSummary(sessionId), ...asObject(payload) };
  return {
    session_id: asString(summary.session_id, sessionId),
    document_type: asString(summary.document_type, "unknown"),
    total_credentials_found: asInteger(summary.total_credentials_found) ?? 0,
    total_credentials_verified: asInteger(summary.total_credentials_verified) ?? 0,
    green_count: asInteger(summary.green_count) ?? 0,
    amber_count: asInteger(summary.amber_count) ?? 0,
    red_count: asInteger(summary.red_count) ?? 0,
    manual_review_count: asInteger(summary.manual_review_count) ?? 0,
    overall_outcome: asNullableString(summary.overall_outcome),
    overall_reason_codes: asStringArray(summary.overall_reason_codes),
  };
}

export function normalizeAnalysisStatus(payload, sessionId = "") {
  const status = { ...createEmptyAnalysisStatus(sessionId), ...asObject(payload) };
  return {
    session_id: asString(status.session_id, sessionId),
    workflow_state: asString(status.workflow_state, "UNKNOWN"),
    generalized_analysis_status: asString(status.generalized_analysis_status, "NOT_STARTED"),
    generalized_analysis_error: asNullableString(status.generalized_analysis_error),
    document_profile_available: asBoolean(status.document_profile_available),
    credentials_available: asBoolean(status.credentials_available),
    verification_plan_available: asBoolean(status.verification_plan_available),
    credential_audits_available: asBoolean(status.credential_audits_available),
    verification_summary_available: asBoolean(status.verification_summary_available),
  };
}

export function normalizeVerificationTaskResults(payload, sessionId = "") {
  const collection = { ...createEmptyVerificationTaskResultCollection(sessionId), ...asObject(payload) };
  const results = Array.isArray(collection.results) ? collection.results : [];

  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    results: results.map((result, index) => {
      const normalizedResult = asObject(result);
      return {
        task_id: asString(normalizedResult.task_id, `task-${index + 1}`),
        credential_id: asString(normalizedResult.credential_id, `credential-${index + 1}`),
        verifier_key: asString(normalizedResult.verifier_key, "manual_review"),
        verifier_label: asString(normalizedResult.verifier_label, "Manual review"),
        task_status: asString(normalizedResult.task_status, "PARTIAL"),
        audit_status: asString(normalizedResult.audit_status, "UNVERIFIED"),
        outcome_color: asString(normalizedResult.outcome_color, "amber"),
        explanation: asString(normalizedResult.explanation, "No execution explanation is available."),
        reason_codes: asStringArray(normalizedResult.reason_codes),
        matched_fields: asObject(normalizedResult.matched_fields),
        mismatched_fields: asObject(normalizedResult.mismatched_fields),
        missing_fields: asStringArray(normalizedResult.missing_fields),
        raw_result_summary: asObject(normalizedResult.raw_result_summary),
        confidence: asNumber(normalizedResult.confidence),
        executed_at: asNullableString(normalizedResult.executed_at),
        latency_ms: asInteger(normalizedResult.latency_ms),
        manual_review_recommended: asBoolean(normalizedResult.manual_review_recommended),
      };
    }),
  };
}

export function normalizeCredentialBundles(payload, sessionId = "") {
  const collection = { ...createEmptyCredentialBundleCollection(sessionId), ...asObject(payload) };
  const bundles = Array.isArray(collection.bundles) ? collection.bundles : [];

  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    bundles: bundles.map((bundle, index) => {
      const normalizedBundle = asObject(bundle);
      const bestResult = normalizedBundle.best_result ? normalizeVerificationTaskResults(
        { session_id: sessionId, document_type: collection.document_type, results: [normalizedBundle.best_result] },
        sessionId
      ).results[0] : null;
      const allResults = normalizeVerificationTaskResults(
        { session_id: sessionId, document_type: collection.document_type, results: normalizedBundle.all_results },
        sessionId
      ).results;
      return {
        credential_id: asString(normalizedBundle.credential_id, `credential-${index + 1}`),
        label: asString(normalizedBundle.label, `Credential ${index + 1}`),
        category: asString(normalizedBundle.category, "unknown"),
        selected_task_ids: asStringArray(normalizedBundle.selected_task_ids),
        result_count: asInteger(normalizedBundle.result_count) ?? allResults.length,
        final_audit_status: asString(normalizedBundle.final_audit_status, "UNVERIFIED"),
        final_outcome_color: asString(normalizedBundle.final_outcome_color, "amber"),
        explanation: asString(normalizedBundle.explanation, "No bundle explanation is available."),
        reason_codes: asStringArray(normalizedBundle.reason_codes),
        best_result: bestResult,
        all_results: allResults,
      };
    }),
  };
}

export function normalizeVerificationExecutionStatus(payload, sessionId = "") {
  const status = { ...createEmptyVerificationExecutionStatus(sessionId), ...asObject(payload) };
  return {
    session_id: asString(status.session_id, sessionId),
    workflow_state: asString(status.workflow_state, "UNKNOWN"),
    verification_execution_status: asString(status.verification_execution_status, "NOT_STARTED"),
    verification_execution_error: asNullableString(status.verification_execution_error),
    task_results_available: asBoolean(status.task_results_available),
    credential_bundles_available: asBoolean(status.credential_bundles_available),
    verification_execution_summary_available: asBoolean(status.verification_execution_summary_available),
  };
}

export function normalizeSessionOverview(payload, sessionId = "") {
  const session = { ...createEmptySessionOverview(sessionId), ...asObject(payload) };
  return {
    session_id: asString(session.session_id, sessionId),
    status: asString(session.status, "UNKNOWN"),
    worker_phase: asNullableString(session.worker_phase),
    filename: asNullableString(session.filename),
    document_available: asBoolean(session.document_available),
    trust_outcome: asNullableString(session.trust_outcome),
    reason_codes: asStringArray(session.reason_codes),
    connector_ids: asStringArray(session.connector_ids),
    generalized_analysis_status: asNullableString(session.generalized_analysis_status),
    generalized_analysis_error: asNullableString(session.generalized_analysis_error),
    purge_status: asNullableString(session.purge_status),
    purge_error: asNullableString(session.purge_error),
    created_at: asNullableString(session.created_at),
    uploaded_at: asNullableString(session.uploaded_at),
    verified_at: asNullableString(session.verified_at),
    closed_at: asNullableString(session.closed_at),
  };
}
