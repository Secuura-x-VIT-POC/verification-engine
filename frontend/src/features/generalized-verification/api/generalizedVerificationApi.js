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
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/document-profile`, { token });
	// return normalizeDocumentProfile(payload, sessionId);
	return null;
}

export async function getCredentials(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/credentials`, { token });
	// return normalizeCredentialCollection(payload, sessionId);
	return null;
}

export async function getVerificationPlan(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/verification-plan`, { token });
	// return normalizeVerificationPlan(payload, sessionId);
	return null;
}

export async function getCredentialAudits(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/credential-audits`, { token });
	// return normalizeCredentialAudits(payload, sessionId);
	return null;
}

export async function getVerificationTaskResults(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/verification-task-results`, { token });
	// return normalizeVerificationTaskResults(payload, sessionId);
	return null;
}

export async function getCredentialBundles(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/credential-bundles`, { token });
	// return normalizeCredentialBundles(payload, sessionId);
	return null;
}

export async function getVerificationSummary(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/verification-summary`, { token });
	// return normalizeVerificationSummary(payload, sessionId);
	return null;
}

export async function getAnalysisStatus(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/analysis-status`, { token });
	// return normalizeAnalysisStatus(payload, sessionId);
	return null;
}

export async function getAgentDocumentUnderstanding(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/agent-document-understanding`, { token });
	// return normalizeAgentDocumentUnderstanding(payload, sessionId);
	return null;
}

export async function getAgentCredentialCandidates(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/agent-credential-candidates`, { token });
	// return normalizeAgentCredentialCandidates(payload, sessionId);
	return null;
}

export async function getAgentRouteRecommendations(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/agent-route-recommendations`, { token });
	// return normalizeAgentRouteRecommendations(payload, sessionId);
	return null;
}

export async function getAgentRunStatus(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/agent-run-status`, { token });
	// return normalizeAgentRunStatus(payload, sessionId);
	return null;
}

export async function getVerificationExecutionStatus(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/verification-execution-status`, { token });
	// return normalizeVerificationExecutionStatus(payload, sessionId);
	return null;
}

export async function getProviderExecutionTraces(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/provider-execution-traces`, { token });
	// return normalizeProviderExecutionTraces(payload, sessionId);
	return null;
}

export async function getProviderExecutionStatus(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/provider-execution-status`, { token });
	// return normalizeProviderExecutionStatus(payload, sessionId);
	return null;
}

export async function getProviderOperatingMode(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/provider-operating-mode`, { token });
	// return normalizeProviderOperatingMode(payload, sessionId);
	return null;
}

export async function getProviderCapabilities(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/provider-capabilities`, { token });
	// return normalizeProviderCapabilities(payload, sessionId);
	return null;
}

export async function getDemoProfile(sessionId, token) {
	// DEPRECATED: backend removed this endpoint (410)
	// const payload = await apiRequest(`/session/${sessionId}/demo-profile`, { token });
	// return normalizeDemoProfile(payload, sessionId);
	return null;
}

export async function getSessionDocumentBlob(sessionId, token) {
	return apiRequest(`/sessions/${sessionId}/document`, { token });
}
