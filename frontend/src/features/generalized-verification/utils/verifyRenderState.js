import { hasUploadAutoRunIntent } from "./autoRun.js";
import { isWorkspaceFailed, isWorkspaceProcessing } from "./noticeClassification.js";

function hasReviewWorkspace(workspace, finalReviewStatuses = new Set()) {
	return Boolean(
		workspace &&
			(workspace.status === "PENDING_HUMAN_REVIEW" ||
				finalReviewStatuses.has(workspace.status) ||
				workspace.fields?.length ||
				workspace.verifiers?.length)
	);
}

export function shouldShowVerificationProcessing({
	autoRunBootstrapping = false,
	autoRunStarting = false,
	isRunInProgress = false,
	isManualRunInProgress = false,
	navigationState = null,
	sessionId = "",
	workspace = null,
	normalizedStatus = "",
} = {}) {
	return Boolean(
		autoRunBootstrapping ||
			autoRunStarting ||
			isRunInProgress ||
			isManualRunInProgress ||
			hasUploadAutoRunIntent({ navigationState, sessionId }) ||
			isWorkspaceProcessing(workspace) ||
			String(normalizedStatus || "").trim().toUpperCase() === "VERIFYING"
	);
}

export function getVerifyMainCardState({
	canRunVerification = false,
	finalReviewStatuses,
	isLoading = false,
	isWorkspacePending = false,
	runError = "",
	shouldShowProcessing = false,
	workspace = null,
} = {}) {
	if (shouldShowProcessing) {
		return "processing";
	}

	const hasGeneratedReviewWorkspace = hasReviewWorkspace(
		workspace,
		finalReviewStatuses
	);

	if (runError || (isWorkspaceFailed(workspace) && !hasGeneratedReviewWorkspace)) {
		return canRunVerification ? "run_error_retry" : "run_error";
	}

	if (isWorkspacePending && !workspace && !isLoading) {
		return "manual_run";
	}

	return "workspace";
}
