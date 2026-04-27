import { apiRequest } from "../../../lib/api.js";

export async function getVerificationWorkspace(sessionId, token) {
	return apiRequest(`/api/v1/verification-sessions/${sessionId}/workspace`, {
		method: "GET",
		token,
	});
}

export async function getSessionDocumentBlob(sessionId, token) {
	return apiRequest(`/sessions/${sessionId}/document`, { token });
}
