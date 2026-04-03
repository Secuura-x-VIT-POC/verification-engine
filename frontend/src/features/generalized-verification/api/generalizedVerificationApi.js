import { apiRequest } from "../../../lib/api.js";
import {
  normalizeAnalysisStatus,
  normalizeCredentialBundles,
  normalizeCredentialAudits,
  normalizeCredentialCollection,
  normalizeDocumentProfile,
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

export async function getVerificationExecutionStatus(sessionId, token) {
  const payload = await apiRequest(`/session/${sessionId}/verification-execution-status`, { token });
  return normalizeVerificationExecutionStatus(payload, sessionId);
}

export async function getSessionDocumentBlob(sessionId, token) {
  return apiRequest(`/sessions/${sessionId}/document`, { token });
}
