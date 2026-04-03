export const DOCUMENT_COORDINATE_BASE = Object.freeze({
  width: 600,
  height: 800,
});

export const AUDIT_STATUS_META = Object.freeze({
  VERIFIED: Object.freeze({ label: "Verified", color: "green" }),
  MISMATCH: Object.freeze({ label: "Mismatch", color: "red" }),
  PARTIAL: Object.freeze({ label: "Partial", color: "amber" }),
  UNVERIFIED: Object.freeze({ label: "Unverified", color: "amber" }),
  MANUAL_REVIEW: Object.freeze({ label: "Manual review", color: "amber" }),
  NOT_APPLICABLE: Object.freeze({ label: "Not applicable", color: "neutral" }),
});

export const ANALYSIS_STATUS_META = Object.freeze({
  NOT_STARTED: "Not started",
  PROFILED: "Profiled",
  CREDENTIALS_BUILT: "Credentials built",
  PLAN_BUILT: "Plan built",
  AUDITS_ASSEMBLED: "Audits assembled",
  READY: "Ready",
  FAILED: "Failed",
});

export const EXECUTION_STATUS_META = Object.freeze({
  NOT_STARTED: "Not started",
  RUNNING: "Running",
  READY: "Ready",
  FAILED: "Failed",
});

export const TASK_STATUS_META = Object.freeze({
  SUCCEEDED: "Succeeded",
  PARTIAL: "Partial",
  FAILED: "Failed",
  MANUAL_REVIEW: "Manual review",
  SKIPPED: "Skipped",
});

export function createEmptyDocumentProfile(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    document_family: "unknown",
    page_count: null,
    extraction_methods_used: [],
    pii_detected: false,
    detected_categories: [],
    requires_manual_review: false,
    notes: [],
  };
}

export function createEmptyCredentialCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    credentials: [],
  };
}

export function createEmptyVerificationPlan(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    route_decisions: [],
    tasks: [],
  };
}

export function createEmptyCredentialAuditCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    audits: [],
  };
}

export function createEmptyVerificationSummary(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    total_credentials_found: 0,
    total_credentials_verified: 0,
    green_count: 0,
    amber_count: 0,
    red_count: 0,
    manual_review_count: 0,
    overall_outcome: null,
    overall_reason_codes: [],
  };
}

export function createEmptyAnalysisStatus(sessionId = "") {
  return {
    session_id: sessionId,
    workflow_state: "UNKNOWN",
    generalized_analysis_status: "NOT_STARTED",
    generalized_analysis_error: null,
    document_profile_available: false,
    credentials_available: false,
    verification_plan_available: false,
    credential_audits_available: false,
    verification_summary_available: false,
  };
}

export function createEmptyVerificationTaskResultCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    results: [],
  };
}

export function createEmptyCredentialBundleCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    bundles: [],
  };
}

export function createEmptyVerificationExecutionStatus(sessionId = "") {
  return {
    session_id: sessionId,
    workflow_state: "UNKNOWN",
    verification_execution_status: "NOT_STARTED",
    verification_execution_error: null,
    task_results_available: false,
    credential_bundles_available: false,
    verification_execution_summary_available: false,
  };
}

export function createEmptySessionOverview(sessionId = "") {
  return {
    session_id: sessionId,
    status: "UNKNOWN",
    worker_phase: null,
    filename: null,
    document_available: false,
    trust_outcome: null,
    reason_codes: [],
    connector_ids: [],
    generalized_analysis_status: null,
    generalized_analysis_error: null,
    purge_status: null,
    purge_error: null,
    created_at: null,
    uploaded_at: null,
    verified_at: null,
    closed_at: null,
  };
}
