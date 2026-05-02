import { apiRequest } from "../../../lib/api.js";

const REVIEW_DECISIONS = new Set([
	"APPROVE",
	"REJECT",
	"NEEDS_MANUAL_REVIEW",
]);

function requireSessionId(sessionId) {
	if (!sessionId) {
		throw new Error("Session ID is required.");
	}
}

export async function runGeneralizedVerification(sessionId, token) {
	requireSessionId(sessionId);

	return apiRequest(`/api/v1/verification-sessions/${sessionId}/run`, {
		method: "POST",
		token,
	});
}

export const runVerificationSession = runGeneralizedVerification;

export async function getVerificationWorkspace(sessionId, token) {
	requireSessionId(sessionId);

	// Important:
	// This function must ONLY fetch workspace.
	// It must NOT call /run automatically.
	// Otherwise approve/review flows can accidentally rerun verification.
	return apiRequest(`/api/v1/verification-sessions/${sessionId}/workspace`, {
		method: "GET",
		token,
	});
}

export async function getSessionDocumentBlob(sessionId, token) {
	requireSessionId(sessionId);

	return apiRequest(`/sessions/${sessionId}/document`, {
		method: "GET",
		token,
	});
}

export async function submitReviewDecision(
	sessionId,
	token,
	decision,
	reviewerNote = ""
) {
	requireSessionId(sessionId);

	const normalizedDecision = String(decision || "").trim().toUpperCase();

	if (!REVIEW_DECISIONS.has(normalizedDecision)) {
		throw new Error(
			"Invalid review decision. Use APPROVE, REJECT, or NEEDS_MANUAL_REVIEW."
		);
	}

	// Important:
	// Approve/Reject/Manual Review should ONLY call review-decision.
	// It should NOT call /run and should NOT reload the page.
	return apiRequest(
		`/api/v1/verification-sessions/${sessionId}/review-decision`,
		{
			method: "POST",
			token,
			body: {
				decision: normalizedDecision,
				reviewer_note: reviewerNote,
			},
		}
	);
}

export async function closeVerificationSession(sessionId, token) {
	requireSessionId(sessionId);

	return apiRequest(`/sessions/${sessionId}/close`, {
		method: "POST",
		token,
	});
}

export function clearRunCache() {
	// Kept only for compatibility with older imports/tests.
}