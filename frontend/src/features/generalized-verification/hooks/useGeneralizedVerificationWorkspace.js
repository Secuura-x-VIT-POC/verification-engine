import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	getSessionDocumentBlob,
	getVerificationWorkspace,
} from "../api/generalizedVerificationApi.js";
import { normalizeWorkspacePayload } from "../utils/workspaceNormalizer.js";

const REFRESH_INTERVAL_MS = 3000;
const MAX_PENDING_RETRIES = 3;
const TERMINAL_UI_STATUSES = new Set([
	"READY",
	"COMPLETED",
	"FAILED",
	"READY FOR HUMAN REVIEW",
]);
const TERMINAL_WORKFLOW_STATUSES = new Set([
	"PENDING_HUMAN_REVIEW",
	"HUMAN_APPROVED",
	"HUMAN_REJECTED",
	"MANUAL_REVIEW_REQUIRED",
	"PENDING_CLEANUP",
	"PURGE_COMPLETE",
	"FAILED_PURGED",
]);
function shouldPoll(workspace) {
	if (!workspace) {
		return false;
	}

	const uiStatus = String(workspace.uiStatus || "").trim().toUpperCase();
	const status = String(workspace.status || "").trim().toUpperCase();

	return (
		!TERMINAL_UI_STATUSES.has(uiStatus) &&
		!TERMINAL_WORKFLOW_STATUSES.has(status)
	);
}

function isWorkspacePendingError(error) {
	return (
		error?.status === 409 &&
		String(error.message || "")
			.toLowerCase()
			.includes("workspace not ready")
	);
}

function getPendingRetryDelay(attempt) {
	return Math.min(1000 * 2 ** attempt, 8000);
}

export function useGeneralizedVerificationWorkspace({ sessionId, token }) {
	const [workspace, setWorkspace] = useState(null);
	const [documentUrl, setDocumentUrl] = useState("");
	const [error, setError] = useState("");
	const [isLoading, setIsLoading] = useState(true);
	const [isWorkspacePending, setIsWorkspacePending] = useState(false);
	const timeoutRef = useRef(null);

	const clearScheduledRefresh = useCallback(() => {
		if (timeoutRef.current) {
			window.clearTimeout(timeoutRef.current);
			timeoutRef.current = null;
		}
	}, []);

	const hydrateWorkspace = useCallback(
		(payload) => {
			const normalizedWorkspace = normalizeWorkspacePayload(payload, sessionId);

			clearScheduledRefresh();
			setWorkspace(normalizedWorkspace);
			setIsWorkspacePending(false);
			setIsLoading(false);
			setError("");

			return normalizedWorkspace;
		},
		[clearScheduledRefresh, sessionId]
	);

	const loadWorkspace = useCallback(
		async ({ showLoading = false, retryOnPending = false, pendingAttempt = 0 } = {}) => {
			if (showLoading) {
				setIsLoading(true);
			}

			setError("");

			try {
				const payload = await getVerificationWorkspace(sessionId, token);
				const normalizedWorkspace = hydrateWorkspace(payload);

				if (shouldPoll(normalizedWorkspace)) {
					timeoutRef.current = window.setTimeout(() => {
						loadWorkspace({ retryOnPending: true });
					}, REFRESH_INTERVAL_MS);
				}

				return normalizedWorkspace;
			} catch (requestError) {
				if (isWorkspacePendingError(requestError)) {
					setIsWorkspacePending(true);
					setIsLoading(false);
					setError("");

					if (retryOnPending && pendingAttempt < MAX_PENDING_RETRIES) {
						timeoutRef.current = window.setTimeout(() => {
							loadWorkspace({
								retryOnPending: true,
								pendingAttempt: pendingAttempt + 1,
							});
						}, getPendingRetryDelay(pendingAttempt));
					}

					return null;
				}

				setError(requestError.message);
				setIsLoading(false);
				return null;
			}
		},
		[hydrateWorkspace, sessionId, token]
	);

	useEffect(() => {
		let isActive = true;
		let objectUrl = "";

		async function loadDocument() {
			try {
				const documentBlob = await getSessionDocumentBlob(sessionId, token);

				if (!isActive || !documentBlob) {
					return;
				}

				objectUrl = URL.createObjectURL(documentBlob);
				setDocumentUrl(objectUrl);
			} catch {
				if (isActive) {
					setDocumentUrl("");
				}
			}
		}

		loadWorkspace({ showLoading: true, retryOnPending: false });
		loadDocument();

		return () => {
			isActive = false;
			clearScheduledRefresh();

			if (objectUrl) {
				URL.revokeObjectURL(objectUrl);
			}
		};
	}, [clearScheduledRefresh, loadWorkspace, sessionId, token]);

	const warnings = useMemo(() => {
		if (!workspace) {
			return [];
		}

		return [
			...workspace.document.warnings,
			...workspace.summary.activeExceptions,
		];
	}, [workspace]);

	return {
		isLoading,
		error: workspace ? "" : error,
		isWorkspacePending,
		warnings,
		documentUrl,
		workspace,
		hydrateWorkspace,
		refreshWorkspace: loadWorkspace,
	};
}
