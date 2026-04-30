import { apiRequest } from "../../../lib/api.js";

const runMap = new Set();

async function ensureRun(sessionId, token) {
	if (runMap.has(sessionId)) return;

	runMap.add(sessionId);

	try {
		await apiRequest(`/api/v1/verification-sessions/${sessionId}/run`, {
			method: "POST",
			token,
		});
	} catch {
		// ignore errors
	}
}

export async function getVerificationWorkspace(sessionId, token) {
	// ✅ ALWAYS ensure run first
	await ensureRun(sessionId, token);

	return apiRequest(`/api/v1/verification-sessions/${sessionId}/workspace`, {
		method: "GET",
		token,
	});
}

export async function getSessionDocumentBlob(sessionId, token) {
	return apiRequest(`/sessions/${sessionId}/document`, {
		method: "GET",
		token,
	});
}