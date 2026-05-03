import {
  createEmptyAgentCredentialCandidateCollection,
  createEmptyAgentDocumentUnderstanding,
  createEmptyAgentRouteRecommendationCollection,
  createEmptyAgentRunStatus,
  createEmptyAnalysisStatus,
  createEmptyCredentialAuditCollection,
  createEmptyCredentialBundleCollection,
  createEmptyCredentialCollection,
  createEmptyDocumentProfile,
  createEmptyDemoProfile,
  createEmptyProviderCapabilityCollection,
  createEmptyProviderExecutionStatus,
  createEmptyProviderOperatingMode,
  createEmptyProviderExecutionTraceCollection,
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
    bbox: Array.isArray(box.bbox) ? box.bbox.map(asNumber) : null,
    polygon: Array.isArray(box.polygon) ? box.polygon : null,
    coordinate_space: asNullableString(box.coordinate_space || box.coordinateSpace),
    source_width: asNumber(box.source_width ?? box.sourceWidth),
    source_height: asNumber(box.source_height ?? box.sourceHeight),
    source: asNullableString(box.source),
  };

  if (normalized.bbox && normalized.bbox.length >= 4) {
    normalized.x0 = normalized.bbox[0];
    normalized.y0 = normalized.bbox[1];
    normalized.x1 = normalized.bbox[2];
    normalized.y1 = normalized.bbox[3];
  }

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
    credentials: credentials
      .map((credential, index) => {
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
      })
      .filter(hasUsableCredentialData),
  };
}

function hasUsableCredentialData(credential) {
  return [credential.value, credential.normalized_value, credential.source_text].some(
    (value) => value !== null && value !== undefined && value !== ""
  );
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
        preferred_provider_key: asNullableString(normalizedDecision.preferred_provider_key),
        preferred_provider_label: asNullableString(normalizedDecision.preferred_provider_label),
        planned_provider_key: asNullableString(normalizedDecision.planned_provider_key),
        planned_provider_label: asNullableString(normalizedDecision.planned_provider_label),
        planned_execution_mode: asNullableString(normalizedDecision.planned_execution_mode),
        planned_is_live_result: asBoolean(normalizedDecision.planned_is_live_result),
        planned_is_mock_result: asBoolean(normalizedDecision.planned_is_mock_result),
        planned_is_demo_result: asBoolean(normalizedDecision.planned_is_demo_result),
        fallback_reason: asNullableString(normalizedDecision.fallback_reason),
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
        preferred_provider_key: asNullableString(normalizedResult.preferred_provider_key),
        preferred_provider_label: asNullableString(normalizedResult.preferred_provider_label),
        planned_provider_key: asNullableString(normalizedResult.planned_provider_key),
        planned_provider_label: asNullableString(normalizedResult.planned_provider_label),
        executed_provider_key: asNullableString(normalizedResult.executed_provider_key),
        executed_provider_label: asNullableString(normalizedResult.executed_provider_label),
        execution_mode: asNullableString(normalizedResult.execution_mode),
        fallback_reason: asNullableString(normalizedResult.fallback_reason),
        is_live_result: asBoolean(normalizedResult.is_live_result),
        is_mock_result: asBoolean(normalizedResult.is_mock_result),
        is_demo_result: asBoolean(normalizedResult.is_demo_result),
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

export function normalizeProviderExecutionTraces(payload, sessionId = "") {
  const collection = { ...createEmptyProviderExecutionTraceCollection(sessionId), ...asObject(payload) };
  const traces = Array.isArray(collection.traces) ? collection.traces : [];
  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    traces: traces.map((trace, index) => {
      const normalizedTrace = asObject(trace);
      return {
        request_id: asString(normalizedTrace.request_id, `trace-${index + 1}`),
        provider_key: asString(normalizedTrace.provider_key, "unknown"),
        verifier_key: asString(normalizedTrace.verifier_key, "unknown"),
        started_at: asNullableString(normalizedTrace.started_at),
        completed_at: asNullableString(normalizedTrace.completed_at),
        technical_status: asString(normalizedTrace.technical_status, "SKIPPED"),
        redaction_applied: asBoolean(normalizedTrace.redaction_applied),
        outbound_mode: asString(normalizedTrace.outbound_mode, "DISABLED"),
        retry_count: asInteger(normalizedTrace.retry_count) ?? 0,
        error_summary: asNullableString(normalizedTrace.error_summary),
        http_status: asInteger(normalizedTrace.http_status),
        response_summary: asObject(normalizedTrace.response_summary),
        fallback_used: asBoolean(normalizedTrace.fallback_used),
        provider_label: asNullableString(normalizedTrace.provider_label),
        provider_operating_mode: asString(normalizedTrace.provider_operating_mode, "LIVE_DISABLED"),
        demo_profile_key: asNullableString(normalizedTrace.demo_profile_key),
        execution_environment_label: asNullableString(normalizedTrace.execution_environment_label),
        transition_notes: asStringArray(normalizedTrace.transition_notes),
        is_mock_result: asBoolean(normalizedTrace.is_mock_result),
        is_demo_result: asBoolean(normalizedTrace.is_demo_result),
        is_live_result: asBoolean(normalizedTrace.is_live_result),
      };
    }),
  };
}

export function normalizeProviderExecutionStatus(payload, sessionId = "") {
  const status = { ...createEmptyProviderExecutionStatus(sessionId), ...asObject(payload) };
  return {
    session_id: asString(status.session_id, sessionId),
    workflow_state: asString(status.workflow_state, "UNKNOWN"),
    provider_execution_status: asString(status.provider_execution_status, "NOT_STARTED"),
    provider_execution_error: asNullableString(status.provider_execution_error),
    traces_available: asBoolean(status.traces_available),
    trace_count: asInteger(status.trace_count) ?? 0,
    provider_keys_used: asStringArray(status.provider_keys_used),
    outbound_attempted: asBoolean(status.outbound_attempted),
    fallback_used: asBoolean(status.fallback_used),
    provider_operating_mode: asString(status.provider_operating_mode, "LIVE_DISABLED"),
    execution_environment_label: asNullableString(status.execution_environment_label),
    demo_profile_key: asNullableString(status.demo_profile_key),
    provider_transition_notes: asStringArray(status.provider_transition_notes),
    live_provider_enabled: asBoolean(status.live_provider_enabled),
    preferred_provider_rail: asString(status.preferred_provider_rail, "entra_verified_id"),
    fallback_policy: asString(status.fallback_policy, "SUPPLEMENTARY_THEN_LOCAL_MOCK"),
    manual_review_policy: asString(status.manual_review_policy, "RECOMMEND_ON_UNCERTAINTY"),
  };
}

export function normalizeProviderCapabilities(payload, sessionId = "") {
  const collection = { ...createEmptyProviderCapabilityCollection(sessionId), ...asObject(payload) };
  const capabilities = Array.isArray(collection.capabilities) ? collection.capabilities : [];
  return {
    session_id: asString(collection.session_id, sessionId),
    capabilities: capabilities.map((capability, index) => {
      const normalizedCapability = asObject(capability);
      return {
        provider_key: asString(normalizedCapability.provider_key, `provider-${index + 1}`),
        provider_label: asString(normalizedCapability.provider_label, "Provider"),
        supported_verifier_keys: asStringArray(normalizedCapability.supported_verifier_keys),
        supported_categories: asStringArray(normalizedCapability.supported_categories),
        supports_batch: asBoolean(normalizedCapability.supports_batch),
        supports_partial_match: asBoolean(normalizedCapability.supports_partial_match),
        supports_document_upload: asBoolean(normalizedCapability.supports_document_upload),
        supports_field_lookup: asBoolean(normalizedCapability.supports_field_lookup, true),
        requires_credentials: asBoolean(normalizedCapability.requires_credentials),
        default_timeout_ms: asInteger(normalizedCapability.default_timeout_ms) ?? 0,
        enabled: asBoolean(normalizedCapability.enabled),
        operating_mode: asString(normalizedCapability.operating_mode, "LIVE_DISABLED"),
        execution_environment_label: asNullableString(normalizedCapability.execution_environment_label),
        demo_supported: asBoolean(normalizedCapability.demo_supported),
      };
    }),
  };
}

export function normalizeProviderOperatingMode(payload, sessionId = "") {
  const mode = { ...createEmptyProviderOperatingMode(sessionId), ...asObject(payload) };
  return {
    session_id: asString(mode.session_id, sessionId),
    workflow_state: asString(mode.workflow_state, "UNKNOWN"),
    provider_operating_mode: asString(mode.provider_operating_mode, "LIVE_DISABLED"),
    execution_environment_label: asString(mode.execution_environment_label, "Local environment"),
    demo_profile_key: asNullableString(mode.demo_profile_key),
    preferred_provider_rail: asString(mode.preferred_provider_rail, "entra_verified_id"),
    enabled_provider_modes: asStringArray(mode.enabled_provider_modes),
    live_provider_enabled: asBoolean(mode.live_provider_enabled),
    fallback_policy: asString(mode.fallback_policy, "SUPPLEMENTARY_THEN_LOCAL_MOCK"),
    manual_review_policy: asString(mode.manual_review_policy, "RECOMMEND_ON_UNCERTAINTY"),
    provider_transition_notes: asStringArray(mode.provider_transition_notes),
  };
}

export function normalizeDemoProfile(payload, sessionId = "") {
  const profile = { ...createEmptyDemoProfile(sessionId), ...asObject(payload) };
  return {
    session_id: asString(profile.session_id, sessionId),
    profile_key: asNullableString(profile.profile_key),
    profile_label: asString(profile.profile_label, "No seeded demo profile"),
    description: asString(profile.description, "No seeded demo profile is active for this session."),
    scenario_family: asString(profile.scenario_family, "none"),
    provider_operating_mode: asString(profile.provider_operating_mode, "LIVE_DISABLED"),
    seeded: asBoolean(profile.seeded),
    notes: asStringArray(profile.notes),
  };
}

export function normalizeAgentDocumentUnderstanding(payload, sessionId = "") {
  const understanding = { ...createEmptyAgentDocumentUnderstanding(sessionId), ...asObject(payload) };
  const detectedEntities = Array.isArray(understanding.detected_entities) ? understanding.detected_entities : [];
  return {
    session_id: asString(understanding.session_id, sessionId),
    document_type_guess: asString(understanding.document_type_guess, "unknown"),
    document_family_guess: asString(understanding.document_family_guess, "unknown"),
    confidence: asNumber(understanding.confidence),
    detected_sections: asStringArray(understanding.detected_sections),
    detected_entities: detectedEntities.map((entity) => {
      const normalizedEntity = asObject(entity);
      return {
        label: asString(normalizedEntity.label, "Unknown"),
        category: asString(normalizedEntity.category, "unknown"),
        credential_id: asNullableString(normalizedEntity.credential_id),
      };
    }),
    pii_signals: asStringArray(understanding.pii_signals),
    credential_candidates: asStringArray(understanding.credential_candidates),
    reasoning_summary: asString(
      understanding.reasoning_summary,
      "No agent document understanding is available."
    ),
    manual_review_recommended: asBoolean(understanding.manual_review_recommended),
  };
}

export function normalizeAgentCredentialCandidates(payload, sessionId = "") {
  const collection = { ...createEmptyAgentCredentialCandidateCollection(sessionId), ...asObject(payload) };
  const candidates = Array.isArray(collection.candidates) ? collection.candidates : [];
  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    candidates: candidates.map((candidate, index) => {
      const normalizedCandidate = asObject(candidate);
      return {
        candidate_id: asString(normalizedCandidate.candidate_id, `candidate-${index + 1}`),
        label: asString(normalizedCandidate.label, `Candidate ${index + 1}`),
        category: asString(normalizedCandidate.category, "unknown"),
        source_fields: asStringArray(normalizedCandidate.source_fields),
        grouped_field_ids: asStringArray(normalizedCandidate.grouped_field_ids),
        grouped_values: asObject(normalizedCandidate.grouped_values),
        confidence: asNumber(normalizedCandidate.confidence),
        verification_recommended: asBoolean(normalizedCandidate.verification_recommended),
        verification_reason: asNullableString(normalizedCandidate.verification_reason),
        possible_verifier_keys: asStringArray(normalizedCandidate.possible_verifier_keys),
        ambiguity_flags: asStringArray(normalizedCandidate.ambiguity_flags),
      };
    }),
  };
}

export function normalizeAgentRouteRecommendations(payload, sessionId = "") {
  const collection = { ...createEmptyAgentRouteRecommendationCollection(sessionId), ...asObject(payload) };
  const recommendations = Array.isArray(collection.recommendations) ? collection.recommendations : [];
  return {
    session_id: asString(collection.session_id, sessionId),
    document_type: asString(collection.document_type, "unknown"),
    recommendations: recommendations.map((recommendation, index) => {
      const normalizedRecommendation = asObject(recommendation);
      return {
        candidate_id: asString(normalizedRecommendation.candidate_id, `candidate-${index + 1}`),
        recommended_verifier_key: asString(normalizedRecommendation.recommended_verifier_key, "manual_review"),
        alternative_verifier_keys: asStringArray(normalizedRecommendation.alternative_verifier_keys),
        route_reason: asString(normalizedRecommendation.route_reason, "No agent route reason is available."),
        confidence: asNumber(normalizedRecommendation.confidence),
        manual_review_recommended: asBoolean(normalizedRecommendation.manual_review_recommended),
      };
    }),
  };
}

export function normalizeAgentRunStatus(payload, sessionId = "") {
  const status = { ...createEmptyAgentRunStatus(sessionId), ...asObject(payload) };
  return {
    session_id: asString(status.session_id, sessionId),
    workflow_state: asString(status.workflow_state, "UNKNOWN"),
    agent_run_status: asString(status.agent_run_status, "NOT_STARTED"),
    agent_run_error: asNullableString(status.agent_run_error),
    provider_used: asNullableString(status.provider_used),
    reasoning_model_used: asNullableString(status.reasoning_model_used),
    pii_model_used: asNullableString(status.pii_model_used),
    pii_enrichment_used: asBoolean(status.pii_enrichment_used),
    fallback_used: asBoolean(status.fallback_used),
    warnings: asStringArray(status.warnings),
    document_understanding_available: asBoolean(status.document_understanding_available),
    credential_candidates_available: asBoolean(status.credential_candidates_available),
    route_recommendations_available: asBoolean(status.route_recommendations_available),
    explanations_available: asBoolean(status.explanations_available),
    run_summary_available: asBoolean(status.run_summary_available),
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
    agent_run_status: asNullableString(session.agent_run_status),
    agent_run_error: asNullableString(session.agent_run_error),
    provider_execution_status: asNullableString(session.provider_execution_status),
    provider_execution_error: asNullableString(session.provider_execution_error),
    provider_operating_mode: asNullableString(session.provider_operating_mode),
    demo_profile_key: asNullableString(session.demo_profile_key),
    execution_environment_label: asNullableString(session.execution_environment_label),
    provider_transition_notes: asStringArray(session.provider_transition_notes),
    purge_status: asNullableString(session.purge_status),
    purge_error: asNullableString(session.purge_error),
    created_at: asNullableString(session.created_at),
    uploaded_at: asNullableString(session.uploaded_at),
    verified_at: asNullableString(session.verified_at),
    closed_at: asNullableString(session.closed_at),
  };
}
