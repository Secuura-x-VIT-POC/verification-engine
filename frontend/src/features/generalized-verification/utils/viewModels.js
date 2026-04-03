import {
  AGENT_RUN_STATUS_META,
  ANALYSIS_STATUS_META,
  AUDIT_STATUS_META,
  DOCUMENT_COORDINATE_BASE,
  EXECUTION_STATUS_META,
  PROVIDER_EXECUTION_STATUS_META,
  TASK_STATUS_META,
} from "../types/contracts.js";

const KNOWN_LABELS = Object.freeze({
  entra_verified_id: "Microsoft Entra Verified ID",
  identity_http: "Supplementary Identity HTTP Provider",
  academic_registry_http: "Supplementary Academic Registry HTTP Provider",
  local_mock: "Local Mock Provider",
});

function toDisplayText(value, fallback = "Not available") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

function clampPercent(value) {
  return Math.max(0, Math.min(value, 100));
}

function createMapByCredentialId(items, key = "credential_id") {
  const entries = Array.isArray(items) ? items : [];
  return entries.reduce((lookup, item) => {
    if (item?.[key]) {
      lookup[item[key]] = item;
    }
    return lookup;
  }, {});
}

function createRouteLookup(plan) {
  return {
    routeByCredentialId: createMapByCredentialId(plan.route_decisions),
    taskByCredentialId: createMapByCredentialId(plan.tasks, "credential_id"),
  };
}

function createBundleLookup(bundleCollection) {
  return createMapByCredentialId(bundleCollection?.bundles || []);
}

function createFallbackAuditDetail(credential, plan) {
  const { routeByCredentialId, taskByCredentialId } = createRouteLookup(plan);
  const routeDecision = routeByCredentialId[credential.credential_id];
  const task = taskByCredentialId[credential.credential_id];
  const auditStatus = credential.requires_verification ? "UNVERIFIED" : "NOT_APPLICABLE";
  const explanation = credential.requires_verification
    ? "Audit not yet available for this extracted credential."
    : "This extracted field is not currently marked for verification.";
  const outcomeColor = auditStatus === "NOT_APPLICABLE" ? "neutral" : "amber";

  return {
    credentialId: credential.credential_id,
    label: credential.label,
    documentValue: toDisplayText(credential.value),
    normalizedValue: credential.normalized_value || null,
    category: credential.category,
    verifierLabel:
      routeDecision?.selected_verifier_label ||
      task?.verifier_label ||
      (credential.requires_verification ? "Verifier pending" : "Not applicable"),
    auditStatus,
    outcomeColor,
    explanation,
    reasonCodes: task?.reason_codes || [],
    matchedFields: {},
    mismatchedFields: {},
    missingFields: [],
    evidence: [],
    timestamp: null,
    requiresVerification: credential.requires_verification,
    verificationReason: credential.verification_reason,
    routeReason: routeDecision?.route_reason || null,
    isFallback: true,
    execution: null,
  };
}

export function buildAuditStatusBadgeModel(status, outcomeColor) {
  const meta = AUDIT_STATUS_META[status] || {
    label: status || "Unknown",
    color: outcomeColor || "neutral",
  };
  return {
    status: status || "UNKNOWN",
    label: meta.label,
    tone: outcomeColor || meta.color,
  };
}

export function buildAnalysisStatusLabel(status) {
  return ANALYSIS_STATUS_META[status] || status || "Unknown";
}

export function buildExecutionStatusLabel(status) {
  return EXECUTION_STATUS_META[status] || status || "Unknown";
}

export function buildProviderExecutionStatusLabel(status) {
  return PROVIDER_EXECUTION_STATUS_META[status] || status || "Unknown";
}

export function buildAgentStatusLabel(status) {
  return AGENT_RUN_STATUS_META[status] || status || "Unknown";
}

function buildExecutionInfo(bundle) {
  if (!bundle) {
    return null;
  }

  const taskStatus = bundle.best_result?.task_status || "NOT_STARTED";
  const rawSummary = bundle.best_result?.raw_result_summary || {};
  return {
    status: taskStatus,
    label: TASK_STATUS_META[taskStatus] || taskStatus,
    resultCount: bundle.result_count,
    confidence: bundle.best_result?.confidence ?? null,
    verifierKey: bundle.best_result?.verifier_key || null,
    selectedTaskIds: bundle.selected_task_ids,
    providerKey: rawSummary.provider_key || null,
    providerLabel: rawSummary.provider_label || labelFromKey(rawSummary.provider_key),
    providerTechnicalStatus: rawSummary.provider_technical_status || null,
    providerLatencyMs: rawSummary.provider_latency_ms ?? null,
    providerFallbackUsed: Boolean(rawSummary.provider_fallback_used),
  };
}

function createAgentCandidateLookup(candidateCollection) {
  const candidates = Array.isArray(candidateCollection?.candidates) ? candidateCollection.candidates : [];
  return candidates.reduce((lookup, candidate) => {
    const fieldIds = Array.isArray(candidate.grouped_field_ids) ? candidate.grouped_field_ids : [];
    fieldIds.forEach((credentialId) => {
      const current = lookup[credentialId];
      if (!current || (candidate.confidence || 0) > (current.confidence || 0)) {
        lookup[credentialId] = candidate;
      }
    });
    return lookup;
  }, {});
}

function createAgentRouteLookup(routeCollection) {
  const recommendations = Array.isArray(routeCollection?.recommendations) ? routeCollection.recommendations : [];
  return recommendations.reduce((lookup, recommendation) => {
    if (recommendation?.candidate_id) {
      lookup[recommendation.candidate_id] = recommendation;
    }
    return lookup;
  }, {});
}

function labelFromVerifierKey(verifierKey) {
  return labelFromKey(verifierKey);
}

function labelFromKey(key) {
  if (!key) {
    return null;
  }
  if (KNOWN_LABELS[key]) {
    return KNOWN_LABELS[key];
  }
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function buildRouteProviderInfo(routeDecision, task) {
  const inputPayload = task?.input_payload || {};
  const preferredProviderKey = routeDecision?.preferred_provider_key || inputPayload.preferred_provider_key || null;
  const preferredProviderLabel =
    routeDecision?.preferred_provider_label || inputPayload.preferred_provider_label || labelFromKey(preferredProviderKey);
  const plannedProviderKey = routeDecision?.planned_provider_key || inputPayload.planned_provider_key || null;
  const plannedProviderLabel =
    routeDecision?.planned_provider_label || inputPayload.planned_provider_label || labelFromKey(plannedProviderKey);

  let routeDispositionLabel = null;
  let routeDispositionMessage = null;

  if (preferredProviderKey === "entra_verified_id" && plannedProviderKey === "entra_verified_id") {
    routeDispositionLabel = "Entra-first route";
    routeDispositionMessage = `${preferredProviderLabel} is the primary VC trust rail for this credential in the current environment.`;
  } else if (preferredProviderKey === "entra_verified_id" && plannedProviderKey && plannedProviderKey !== "local_mock") {
    routeDispositionLabel = "Supplementary route";
    routeDispositionMessage = `${preferredProviderLabel} is preferred for this credential, but ${plannedProviderLabel} is the current supplementary execution path.`;
  } else if (preferredProviderKey === "entra_verified_id" && plannedProviderKey === "local_mock") {
    routeDispositionLabel = "Entra unavailable";
    routeDispositionMessage = `${preferredProviderLabel} is preferred for this credential, but it is not enabled here, so the bounded local mock path is planned.`;
  } else if (plannedProviderKey === "local_mock") {
    routeDispositionLabel = "Local fallback";
    routeDispositionMessage = "No external provider is enabled for this route, so the bounded local mock path is planned.";
  } else if (plannedProviderKey) {
    routeDispositionLabel = "Supplementary route";
    routeDispositionMessage = `${plannedProviderLabel} is the planned provider path for this credential.`;
  } else if (routeDecision?.selected_verifier_key === "manual_review") {
    routeDispositionLabel = "Manual review";
    routeDispositionMessage = "No executable provider path is available for this credential.";
  }

  return {
    preferredProviderKey,
    preferredProviderLabel,
    plannedProviderKey,
    plannedProviderLabel,
    routeDispositionLabel,
    routeDispositionMessage,
  };
}

function buildAgentInfo(credentialId, candidateLookup, routeLookup) {
  const candidate = candidateLookup[credentialId];
  if (!candidate) {
    return null;
  }
  const recommendation = routeLookup[candidate.candidate_id] || null;
  return {
    candidateId: candidate.candidate_id,
    candidateLabel: candidate.label,
    category: candidate.category,
    confidence: candidate.confidence,
    verificationReason: candidate.verification_reason,
    groupedFieldIds: candidate.grouped_field_ids || [],
    recommendedVerifierKey: recommendation?.recommended_verifier_key || null,
    recommendedVerifierLabel: labelFromVerifierKey(recommendation?.recommended_verifier_key),
    alternativeVerifierKeys: recommendation?.alternative_verifier_keys || [],
    routeReason: recommendation?.route_reason || null,
    manualReviewRecommended: Boolean(recommendation?.manual_review_recommended),
  };
}

function extractAgentExplanation(evidence) {
  const items = Array.isArray(evidence) ? evidence : [];
  const match = items.find((item) => item?.source === "agent_orchestration");
  return match?.detail?.summary || null;
}

export function buildAuditDetailViewModels(
  credentialsResponse,
  auditCollection,
  planResponse,
  bundleCollection,
  candidateCollection,
  routeCollection
) {
  const credentials = Array.isArray(credentialsResponse.credentials) ? credentialsResponse.credentials : [];
  const audits = Array.isArray(auditCollection.audits) ? auditCollection.audits : [];
  const auditLookup = createMapByCredentialId(audits);
  const { routeByCredentialId, taskByCredentialId } = createRouteLookup(planResponse);
  const bundleLookup = createBundleLookup(bundleCollection);
  const agentCandidateLookup = createAgentCandidateLookup(candidateCollection);
  const agentRouteLookup = createAgentRouteLookup(routeCollection);

  return credentials.map((credential) => {
    const audit = auditLookup[credential.credential_id];
    const routeDecision = routeByCredentialId[credential.credential_id];
    const task = taskByCredentialId[credential.credential_id];
    const bundle = bundleLookup[credential.credential_id];
    const agentInfo = buildAgentInfo(credential.credential_id, agentCandidateLookup, agentRouteLookup);
    const routeProviderInfo = buildRouteProviderInfo(routeDecision, task);

    if (!audit && !bundle) {
      const detail = createFallbackAuditDetail(credential, planResponse);
      return {
        ...detail,
        ...routeProviderInfo,
        agentAssisted: Boolean(agentInfo),
        agentInfo,
        agentExplanation: null,
      };
    }

    if (!audit && bundle) {
      const bestResult = bundle.best_result;
      return {
        credentialId: credential.credential_id,
        label: bundle.label || credential.label,
        documentValue: toDisplayText(credential.value),
        normalizedValue: credential.normalized_value || null,
        category: credential.category,
        verifierLabel: bestResult?.verifier_label || routeDecision?.selected_verifier_label || "Verifier unavailable",
        auditStatus: bundle.final_audit_status,
        outcomeColor: bundle.final_outcome_color,
        explanation: bundle.explanation,
        reasonCodes: bundle.reason_codes,
        matchedFields: bestResult?.matched_fields || {},
        mismatchedFields: bestResult?.mismatched_fields || {},
        missingFields: bestResult?.missing_fields || [],
        evidence: [],
        timestamp: bestResult?.executed_at || null,
        requiresVerification: credential.requires_verification,
        verificationReason: credential.verification_reason,
        routeReason: routeDecision?.route_reason || null,
        isFallback: false,
        execution: buildExecutionInfo(bundle),
        ...routeProviderInfo,
        agentAssisted: Boolean(agentInfo),
        agentInfo,
        agentExplanation: null,
      };
    }

    return {
      credentialId: credential.credential_id,
      label: audit.label || credential.label,
      documentValue: toDisplayText(audit.document_value ?? credential.value),
      normalizedValue: audit.normalized_value || credential.normalized_value || null,
      category: credential.category,
      verifierLabel:
        audit.verifier_label ||
        routeDecision?.selected_verifier_label ||
        task?.verifier_label ||
        "Verifier unavailable",
      auditStatus: audit.audit_status,
      outcomeColor: audit.outcome_color,
      explanation: audit.explanation,
      reasonCodes: audit.reason_codes,
      matchedFields: audit.matched_fields,
      mismatchedFields: audit.mismatched_fields,
      missingFields: audit.missing_fields,
      evidence: audit.evidence,
      timestamp: audit.timestamp,
      requiresVerification: credential.requires_verification,
      verificationReason: credential.verification_reason,
      routeReason: routeDecision?.route_reason || null,
      isFallback: false,
      execution: buildExecutionInfo(bundle),
      ...routeProviderInfo,
      agentAssisted: Boolean(agentInfo) || Boolean(extractAgentExplanation(audit.evidence)),
      agentInfo,
      agentExplanation: extractAgentExplanation(audit.evidence),
    };
  });
}

export function buildAnalysisRows(
  credentialsResponse,
  planResponse,
  auditCollection,
  bundleCollection,
  candidateCollection,
  routeCollection
) {
  const details = buildAuditDetailViewModels(
    credentialsResponse,
    auditCollection,
    planResponse,
    bundleCollection,
    candidateCollection,
    routeCollection
  );
  const detailLookup = details.reduce((lookup, detail) => {
    lookup[detail.credentialId] = detail;
    return lookup;
  }, {});
  const { routeByCredentialId, taskByCredentialId } = createRouteLookup(planResponse);

  return credentialsResponse.credentials.map((credential) => {
    const detail = detailLookup[credential.credential_id];
    const routeDecision = routeByCredentialId[credential.credential_id];
    const task = taskByCredentialId[credential.credential_id];

    return {
      credentialId: credential.credential_id,
      label: credential.label,
      category: credential.category,
      extractedValue: toDisplayText(credential.value),
      normalizedValue: credential.normalized_value || null,
      requiresVerification: credential.requires_verification,
      verificationReason: credential.verification_reason,
      verifierLabel:
        routeDecision?.selected_verifier_label ||
        task?.verifier_label ||
        detail?.verifierLabel ||
        "Pending route",
      auditStatus: detail?.auditStatus || "UNVERIFIED",
      outcomeColor: detail?.outcomeColor || "amber",
      reasonCodes: detail?.reasonCodes || task?.reason_codes || [],
      routeReason: routeDecision?.route_reason || null,
      taskStatus: detail?.execution?.status || null,
      preferredProviderKey: detail?.preferredProviderKey || null,
      preferredProviderLabel: detail?.preferredProviderLabel || null,
      plannedProviderLabel: detail?.plannedProviderLabel || null,
      routeDispositionLabel: detail?.routeDispositionLabel || null,
      routeDispositionMessage: detail?.routeDispositionMessage || null,
      providerLabel: detail?.execution?.providerLabel || null,
      providerTechnicalStatus: detail?.execution?.providerTechnicalStatus || null,
      providerFallbackUsed: detail?.execution?.providerFallbackUsed || false,
      agentAssisted: detail?.agentAssisted || false,
      agentRecommendedVerifierLabel: detail?.agentInfo?.recommendedVerifierLabel || null,
      agentRouteReason: detail?.agentInfo?.routeReason || null,
      agentManualReviewRecommended: detail?.agentInfo?.manualReviewRecommended || false,
    };
  });
}

export function buildHighlightItems(
  credentialsResponse,
  auditCollection,
  planResponse,
  bundleCollection,
  candidateCollection,
  routeCollection
) {
  const detailLookup = buildAuditDetailViewModels(
    credentialsResponse,
    auditCollection,
    planResponse,
    bundleCollection,
    candidateCollection,
    routeCollection
  ).reduce(
    (lookup, detail) => {
      lookup[detail.credentialId] = detail;
      return lookup;
    },
    {}
  );

  return credentialsResponse.credentials
    .map((credential) => {
      const box = credential.bounding_box;
      if (!box) {
        return null;
      }

      const x0 = Number(box.x0);
      const y0 = Number(box.y0);
      const x1 = Number(box.x1);
      const y1 = Number(box.y1);

      if (![x0, y0, x1, y1].every(Number.isFinite)) {
        return null;
      }

      const width = x1 - x0;
      const height = y1 - y0;
      if (width <= 0 || height <= 0) {
        return null;
      }

      const detail = detailLookup[credential.credential_id] || createFallbackAuditDetail(credential, planResponse);
      return {
        credentialId: credential.credential_id,
        label: credential.label,
        page: box.page || credential.page || 1,
        auditStatus: detail.auditStatus,
        outcomeColor: detail.outcomeColor,
        explanation: detail.explanation,
        documentValue: detail.documentValue,
        hasAudit: !detail.isFallback,
        agentAssisted: detail.agentAssisted,
        relativeBox: {
          left: clampPercent((x0 / DOCUMENT_COORDINATE_BASE.width) * 100),
          top: clampPercent((y0 / DOCUMENT_COORDINATE_BASE.height) * 100),
          width: clampPercent((width / DOCUMENT_COORDINATE_BASE.width) * 100),
          height: clampPercent((height / DOCUMENT_COORDINATE_BASE.height) * 100),
        },
      };
    })
    .filter(Boolean);
}

export function buildStatusCounts(auditDetails) {
  return auditDetails.reduce(
    (counts, detail) => {
      counts[detail.auditStatus] = (counts[detail.auditStatus] || 0) + 1;
      return counts;
    },
    {
      VERIFIED: 0,
      MISMATCH: 0,
      PARTIAL: 0,
      UNVERIFIED: 0,
      MANUAL_REVIEW: 0,
      NOT_APPLICABLE: 0,
    }
  );
}

export function buildRoutingSummary(planResponse) {
  const byVerifier = {};
  for (const decision of planResponse.route_decisions) {
    const label = decision.selected_verifier_label || "Manual review";
    byVerifier[label] = (byVerifier[label] || 0) + 1;
  }

  return Object.entries(byVerifier)
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
}

export function buildTaskExecutionSummary(taskResults, executionStatus) {
  const results = Array.isArray(taskResults?.results) ? taskResults.results : [];
  const executionState = executionStatus?.verification_execution_status || "NOT_STARTED";
  const counts = results.reduce(
    (summary, result) => {
      summary[result.task_status] = (summary[result.task_status] || 0) + 1;
      return summary;
    },
    {
      SUCCEEDED: 0,
      PARTIAL: 0,
      FAILED: 0,
      MANUAL_REVIEW: 0,
      SKIPPED: 0,
    }
  );

  return {
    overallStatus: executionState,
    overallLabel: buildExecutionStatusLabel(executionState),
    totalTasks: results.length,
    counts,
    verifierKeysUsed: Array.from(new Set(results.map((result) => result.verifier_key).filter(Boolean))).sort(),
  };
}

export function buildProviderExecutionSummary(providerExecutionTraces, providerExecutionStatus, providerCapabilities) {
  const traces = Array.isArray(providerExecutionTraces?.traces) ? providerExecutionTraces.traces : [];
  const capabilities = Array.isArray(providerCapabilities?.capabilities) ? providerCapabilities.capabilities : [];
  const entraCapability = capabilities.find((capability) => capability.provider_key === "entra_verified_id") || null;
  const enabledCapabilities = capabilities.filter((capability) => capability.enabled);
  return {
    overallStatus: providerExecutionStatus?.provider_execution_status || "NOT_STARTED",
    overallLabel: buildProviderExecutionStatusLabel(providerExecutionStatus?.provider_execution_status),
    traceCount: traces.length,
    providerKeysUsed: providerExecutionStatus?.provider_keys_used || [],
    outboundAttempted: Boolean(providerExecutionStatus?.outbound_attempted),
    fallbackUsed: Boolean(providerExecutionStatus?.fallback_used),
    enabledProviders: enabledCapabilities.map((capability) => capability.provider_label),
    enabledExternalProviders: enabledCapabilities
      .filter((capability) => capability.provider_key !== "local_mock")
      .map((capability) => capability.provider_label),
    primaryTrustRailLabel: entraCapability?.provider_label || "Microsoft Entra Verified ID",
    primaryTrustRailEnabled: Boolean(entraCapability?.enabled),
  };
}

export function buildAgentUnderstandingSummary(understanding, runStatus) {
  return {
    status: runStatus?.agent_run_status || "NOT_STARTED",
    statusLabel: buildAgentStatusLabel(runStatus?.agent_run_status),
    documentTypeGuess: understanding?.document_type_guess || "unknown",
    documentFamilyGuess: understanding?.document_family_guess || "unknown",
    confidence: understanding?.confidence ?? null,
    reasoningSummary:
      understanding?.reasoning_summary || "No agent-assisted document understanding is available.",
    manualReviewRecommended: Boolean(understanding?.manual_review_recommended),
    candidateCount: Array.isArray(understanding?.credential_candidates)
      ? understanding.credential_candidates.length
      : 0,
    providerUsed: runStatus?.provider_used || null,
    fallbackUsed: Boolean(runStatus?.fallback_used),
    warnings: Array.isArray(runStatus?.warnings) ? runStatus.warnings : [],
  };
}

export function buildWorkspaceViewModel({
  session,
  agentDocumentUnderstanding,
  agentCredentialCandidates,
  agentRouteRecommendations,
  agentRunStatus,
  documentProfile,
  credentials,
  verificationPlan,
  verificationTaskResults,
  credentialBundles,
  credentialAudits,
  verificationSummary,
  analysisStatus,
  executionStatus,
  providerExecutionTraces,
  providerExecutionStatus,
  providerCapabilities,
}) {
  const auditDetails = buildAuditDetailViewModels(
    credentials,
    credentialAudits,
    verificationPlan,
    credentialBundles,
    agentCredentialCandidates,
    agentRouteRecommendations
  );
  const analysisRows = buildAnalysisRows(
    credentials,
    verificationPlan,
    credentialAudits,
    credentialBundles,
    agentCredentialCandidates,
    agentRouteRecommendations
  );
  const highlightItems = buildHighlightItems(
    credentials,
    credentialAudits,
    verificationPlan,
    credentialBundles,
    agentCredentialCandidates,
    agentRouteRecommendations
  );
  const statusCounts = buildStatusCounts(auditDetails);
  const routingSummary = buildRoutingSummary(verificationPlan);
  const taskExecutionSummary = buildTaskExecutionSummary(verificationTaskResults, executionStatus);
  const providerExecutionSummary = buildProviderExecutionSummary(
    providerExecutionTraces,
    providerExecutionStatus,
    providerCapabilities
  );
  const entraPreferredInPlan = analysisRows.some((row) => row.preferredProviderKey === "entra_verified_id");
  const agentUnderstandingSummary = buildAgentUnderstandingSummary(agentDocumentUnderstanding, agentRunStatus);
  const selectedCredentialId =
    highlightItems[0]?.credentialId || auditDetails[0]?.credentialId || credentials.credentials[0]?.credential_id || null;

  return {
    credentialItems: auditDetails.map((detail) => ({
      credentialId: detail.credentialId,
      label: detail.label,
      documentValue: detail.documentValue,
      auditStatus: detail.auditStatus,
      outcomeColor: detail.outcomeColor,
    })),
    analysisRows,
    auditDetails,
    highlightItems,
    routingSummary,
    statusCounts,
    selectedCredentialId,
    analysisStatusLabel: buildAnalysisStatusLabel(analysisStatus.generalized_analysis_status),
    executionStatusLabel: buildExecutionStatusLabel(executionStatus.verification_execution_status),
    providerExecutionStatusLabel: buildProviderExecutionStatusLabel(providerExecutionStatus.provider_execution_status),
    agentStatusLabel: buildAgentStatusLabel(agentRunStatus.agent_run_status),
    agentUnderstandingSummary,
    taskExecutionSummary,
    providerExecutionSummary,
    overallOutcome: verificationSummary.overall_outcome || session.trust_outcome || null,
    summaryStats: [
      { label: "Credentials", value: verificationSummary.total_credentials_found || credentials.credentials.length },
      { label: "Verified", value: verificationSummary.total_credentials_verified },
      { label: "Green", value: verificationSummary.green_count },
      { label: "Amber", value: verificationSummary.amber_count },
      { label: "Red", value: verificationSummary.red_count },
      { label: "Manual review", value: verificationSummary.manual_review_count },
    ],
    messages: {
      analysis:
        analysisStatus.generalized_analysis_status !== "READY"
          ? analysisStatus.generalized_analysis_error ||
            "Generalized analysis is not fully ready yet. Read-only fallbacks are shown where possible."
          : null,
      agent:
        agentRunStatus.agent_run_error ||
        (agentRunStatus.agent_run_status !== "READY" && agentRunStatus.agent_run_status !== "NOT_STARTED"
          ? "Agent-assisted enrichment is not fully ready yet. Deterministic planning remains active."
          : null),
      provider:
        providerExecutionStatus.provider_execution_error ||
        (providerExecutionStatus.provider_execution_status === "FAILED"
          ? "Provider-backed execution failed safely. Bounded fallback results are shown where available."
          : entraPreferredInPlan && !providerExecutionSummary.primaryTrustRailEnabled
            ? "Microsoft Entra Verified ID is the preferred VC trust rail for some credentials, but it is not enabled in this environment. Supplementary providers or manual review are shown where applicable."
          : null),
      document: !session.document_available
        ? "No PDF is currently stored for this session."
        : highlightItems.length
          ? null
          : "No overlay-ready bounding boxes are available for the current credentials.",
      credentials: credentials.credentials.length
        ? null
        : "No credentials were extracted for this session from the currently available artifacts.",
      audits: auditDetails.length ? null : "No credential audits are available yet.",
    },
    flags: {
      hasDocument: Boolean(session.document_available),
      hasCredentials: credentials.credentials.length > 0,
      hasAudits: auditDetails.length > 0,
      hasHighlights: highlightItems.length > 0,
      analysisReady: analysisStatus.generalized_analysis_status === "READY",
      agentReady: agentRunStatus.agent_run_status === "READY",
      providerReady: providerExecutionStatus.provider_execution_status === "READY",
    },
    profileNotes: documentProfile.notes,
  };
}

export function getAuditDetailByCredentialId(auditDetails, credentialId) {
  if (!credentialId) {
    return auditDetails[0] || null;
  }
  return auditDetails.find((detail) => detail.credentialId === credentialId) || auditDetails[0] || null;
}
