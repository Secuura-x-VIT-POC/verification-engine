import { apiRequest } from "../../../lib/api.js";
import {
  normalizeAgentCredentialCandidates,
  normalizeAgentDocumentUnderstanding,
  normalizeAgentRouteRecommendations,
  normalizeAgentRunStatus,
  normalizeAnalysisStatus,
  normalizeCredentialBundles,
  normalizeCredentialAudits,
  normalizeCredentialCollection,
  normalizeDocumentProfile,
  normalizeDemoProfile,
  normalizeProviderCapabilities,
  normalizeProviderExecutionStatus,
  normalizeProviderOperatingMode,
  normalizeProviderExecutionTraces,
  normalizeSessionOverview,
  normalizeVerificationExecutionStatus,
  normalizeVerificationPlan,
  normalizeVerificationTaskResults,
  normalizeVerificationSummary,
} from "../utils/normalizers.js";

export async function getSessionOverview(sessionId, token) {
  const payload = await apiRequest(`/sessions/${sessionId}`, { token });
  return normalizeSessionOverview(payload, sessionId);
}

export async function getDocumentProfile(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/document-profile`, { token });
  return normalizeDocumentProfile(payload, sessionId);
}

export async function getCredentials(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/credentials`, { token });
  return normalizeCredentialCollection(payload, sessionId);
}

export async function getVerificationPlan(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/verification-plan`, { token });
  return normalizeVerificationPlan(payload, sessionId);
}

export async function getCredentialAudits(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/credential-audits`, { token });
  return normalizeCredentialAudits(payload, sessionId);
}

export async function getVerificationTaskResults(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/verification-task-results`, { token });
  return normalizeVerificationTaskResults(payload, sessionId);
}

export async function getCredentialBundles(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/credential-bundles`, { token });
  return normalizeCredentialBundles(payload, sessionId);
}

export async function getVerificationSummary(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/verification-summary`, { token });
  return normalizeVerificationSummary(payload, sessionId);
}

export async function getAnalysisStatus(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/analysis-status`, { token });
  return normalizeAnalysisStatus(payload, sessionId);
}

export async function getAgentDocumentUnderstanding(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/agent-document-understanding`, { token });
  return normalizeAgentDocumentUnderstanding(payload, sessionId);
}

export async function getAgentCredentialCandidates(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/agent-credential-candidates`, { token });
  return normalizeAgentCredentialCandidates(payload, sessionId);
}

export async function getAgentRouteRecommendations(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/agent-route-recommendations`, { token });
  return normalizeAgentRouteRecommendations(payload, sessionId);
}

export async function getAgentRunStatus(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/agent-run-status`, { token });
  return normalizeAgentRunStatus(payload, sessionId);
}

export async function getVerificationExecutionStatus(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/verification-execution-status`, { token });
  return normalizeVerificationExecutionStatus(payload, sessionId);
}

export async function getProviderExecutionTraces(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/provider-execution-traces`, { token });
  return normalizeProviderExecutionTraces(payload, sessionId);
}

export async function getProviderExecutionStatus(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/provider-execution-status`, { token });
  return normalizeProviderExecutionStatus(payload, sessionId);
}

export async function getProviderOperatingMode(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/provider-operating-mode`, { token });
  return normalizeProviderOperatingMode(payload, sessionId);
}

export async function getProviderCapabilities(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/provider-capabilities`, { token });
  return normalizeProviderCapabilities(payload, sessionId);
}

export async function getDemoProfile(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/demo-profile`, { token });
  return normalizeDemoProfile(payload, sessionId);
}

export async function getSessionDocumentBlob(sessionId, token) {
  return apiRequest(`/sessions/${sessionId}/document`, { token });
}
