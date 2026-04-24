import { useEffect, useState } from "react";
import {
	getSessionDocumentBlob,
	getSessionOverview,
} from "../api/generalizedVerificationApi.js";
import {
	createEmptyAgentCredentialCandidateCollection,
	createEmptyAgentDocumentUnderstanding,
	createEmptyAgentRouteRecommendationCollection,
	createEmptyAgentRunStatus,
	createEmptyAnalysisStatus,
	createEmptyCredentialBundleCollection,
	createEmptyCredentialAuditCollection,
	createEmptyCredentialCollection,
	createEmptyDocumentProfile,
	createEmptyDemoProfile,
	createEmptyProviderCapabilityCollection,
	createEmptyProviderExecutionStatus,
	createEmptyProviderOperatingMode,
	createEmptyProviderExecutionTraceCollection,
	createEmptySessionOverview,
	createEmptyVerificationExecutionStatus,
	createEmptyVerificationPlan,
	createEmptyVerificationTaskResultCollection,
	createEmptyVerificationSummary,
} from "../types/contracts.js";

function createEmptyWorkspaceData(sessionId) {
	return {
		session: createEmptySessionOverview(sessionId),
		documentProfile: createEmptyDocumentProfile(sessionId),
		credentials: createEmptyCredentialCollection(sessionId),
		verificationPlan: createEmptyVerificationPlan(sessionId),
		verificationTaskResults:
			createEmptyVerificationTaskResultCollection(sessionId),
		credentialBundles: createEmptyCredentialBundleCollection(sessionId),
		credentialAudits: createEmptyCredentialAuditCollection(sessionId),
		verificationSummary: createEmptyVerificationSummary(sessionId),
		analysisStatus: createEmptyAnalysisStatus(sessionId),
		executionStatus: createEmptyVerificationExecutionStatus(sessionId),
		providerExecutionTraces:
			createEmptyProviderExecutionTraceCollection(sessionId),
		providerExecutionStatus: createEmptyProviderExecutionStatus(sessionId),
		providerOperatingMode: createEmptyProviderOperatingMode(sessionId),
		providerCapabilities: createEmptyProviderCapabilityCollection(sessionId),
		demoProfile: createEmptyDemoProfile(sessionId),
		agentDocumentUnderstanding:
			createEmptyAgentDocumentUnderstanding(sessionId),
		agentCredentialCandidates:
			createEmptyAgentCredentialCandidateCollection(sessionId),
		agentRouteRecommendations:
			createEmptyAgentRouteRecommendationCollection(sessionId),
		agentRunStatus: createEmptyAgentRunStatus(sessionId),
	};
}

export function useGeneralizedVerificationWorkspace({ sessionId, token }) {
	const [session, setSession] = useState(null);
	const [documentUrl, setDocumentUrl] = useState("");
	const [error, setError] = useState("");
	const [isLoading, setIsLoading] = useState(true);
	const [warnings, setWarnings] = useState([]);

	const pollSession = async (currentSessionId) => {
		try {
			const res = await fetch(
				`http://localhost:8000/sessions/${currentSessionId}`,
				{
					headers: {
						Authorization: `Bearer ${token}`,
						"Content-Type": "application/json",
					},
				},
			);
			const data = await res.json();

			setSession(data);

			if (
				data.status !== "VERIFIED_GREEN" &&
				data.status !== "VERIFIED_AMBER" &&
				data.status !== "VERIFIED_RED" &&
				data.status !== "FAILED_RETRIABLE"
			) {
				setTimeout(() => pollSession(currentSessionId), 2000);
			}
		} catch (err) {
			setError(err.message);
		}
	};

	useEffect(() => {
		let isActive = true;
		let nextObjectUrl = "";

		async function loadWorkspace() {
			setIsLoading(true);
			setError("");
			setWarnings([]);

			try {
				// Load session data and start polling
				await pollSession(sessionId);

				// Load document if available
				const sessionData = await getSessionOverview(sessionId, token);
				if (!isActive) return;

				if (sessionData.document_available) {
					const documentBlobResult = await getSessionDocumentBlob(
						sessionId,
						token,
					);
					if (documentBlobResult) {
						nextObjectUrl = URL.createObjectURL(documentBlobResult);
					}
				}

				if (isActive) {
					setDocumentUrl(nextObjectUrl);
					setIsLoading(false);
				}
			} catch (requestError) {
				if (isActive) {
					setError(requestError.message);
					setIsLoading(false);
				}
			}
		}

		loadWorkspace();

		return () => {
			isActive = false;
			if (nextObjectUrl) {
				URL.revokeObjectURL(nextObjectUrl);
			}
		};
	}, [sessionId, token]);

	// Create legacy data structure for UI compatibility
	const data = createEmptyWorkspaceData(sessionId);
	if (session) {
		data.session = {
			...data.session,
			...session,
			session_id: sessionId,
		};
	}

	return {
		isLoading,
		error,
		warnings,
		documentUrl,
		data,
	};
}
