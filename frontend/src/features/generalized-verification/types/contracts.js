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

export const PROVIDER_EXECUTION_STATUS_META = Object.freeze({
  NOT_STARTED: "Not started",
  RUNNING: "Running",
  READY: "Ready",
  FAILED: "Failed",
});

export const PROVIDER_OPERATING_MODE_META = Object.freeze({
  DEMO_MOCK: "Demo-mock",
  LOCAL_MOCK: "Local mock",
  EXTERNAL_CONFIGURED: "Live configured",
  LIVE_DISABLED: "Live disabled",
  MANUAL_ONLY: "Manual only",
});

export const AGENT_RUN_STATUS_META = Object.freeze({
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

export function createEmptyProviderExecutionTraceCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    traces: [],
  };
}

export function createEmptyProviderExecutionStatus(sessionId = "") {
  return {
    session_id: sessionId,
    workflow_state: "UNKNOWN",
    provider_execution_status: "NOT_STARTED",
    provider_execution_error: null,
    traces_available: false,
    trace_count: 0,
    provider_keys_used: [],
    outbound_attempted: false,
    fallback_used: false,
    provider_operating_mode: "LIVE_DISABLED",
    execution_environment_label: null,
    demo_profile_key: null,
    provider_transition_notes: [],
    live_provider_enabled: false,
    preferred_provider_rail: "entra_verified_id",
    fallback_policy: "SUPPLEMENTARY_THEN_LOCAL_MOCK",
    manual_review_policy: "RECOMMEND_ON_UNCERTAINTY",
  };
}

export function createEmptyProviderCapabilityCollection(sessionId = "") {
  return {
    session_id: sessionId,
    capabilities: [],
  };
}

export function createEmptyProviderOperatingMode(sessionId = "") {
  return {
    session_id: sessionId,
    workflow_state: "UNKNOWN",
    provider_operating_mode: "LIVE_DISABLED",
    execution_environment_label: "Local environment",
    demo_profile_key: null,
    preferred_provider_rail: "entra_verified_id",
    enabled_provider_modes: [],
    live_provider_enabled: false,
    fallback_policy: "SUPPLEMENTARY_THEN_LOCAL_MOCK",
    manual_review_policy: "RECOMMEND_ON_UNCERTAINTY",
    provider_transition_notes: [],
  };
}

export function createEmptyDemoProfile(sessionId = "") {
  return {
    session_id: sessionId,
    profile_key: null,
    profile_label: "No seeded demo profile",
    description: "No seeded demo profile is active for this session.",
    scenario_family: "none",
    provider_operating_mode: "LIVE_DISABLED",
    seeded: false,
    notes: [],
  };
}

export function createEmptyAgentDocumentUnderstanding(sessionId = "") {
  return {
    session_id: sessionId,
    document_type_guess: "unknown",
    document_family_guess: "unknown",
    confidence: null,
    detected_sections: [],
    detected_entities: [],
    pii_signals: [],
    credential_candidates: [],
    reasoning_summary: "No agent document understanding is available.",
    manual_review_recommended: false,
  };
}

export function createEmptyAgentCredentialCandidateCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    candidates: [],
  };
}

export function createEmptyAgentRouteRecommendationCollection(sessionId = "") {
  return {
    session_id: sessionId,
    document_type: "unknown",
    recommendations: [],
  };
}

export function createEmptyAgentRunStatus(sessionId = "") {
  return {
    session_id: sessionId,
    workflow_state: "UNKNOWN",
    agent_run_status: "NOT_STARTED",
    agent_run_error: null,
    provider_used: null,
    fallback_used: false,
    warnings: [],
    document_understanding_available: false,
    credential_candidates_available: false,
    route_recommendations_available: false,
    explanations_available: false,
    run_summary_available: false,
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
    agent_run_status: null,
    agent_run_error: null,
    provider_execution_status: null,
    provider_execution_error: null,
    provider_operating_mode: null,
    demo_profile_key: null,
    execution_environment_label: null,
    provider_transition_notes: [],
    purge_status: null,
    purge_error: null,
    created_at: null,
    uploaded_at: null,
    verified_at: null,
    closed_at: null,
  };
}
