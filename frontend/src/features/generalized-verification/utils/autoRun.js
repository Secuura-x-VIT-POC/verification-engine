export const AUTO_RUN_READY_UPLOAD_STATUS = "UPLOADED_PENDING_REVIEW";

export function hasUploadAutoRunIntent({ navigationState, sessionId }) {
	return Boolean(
		navigationState?.autoRunAfterUpload === true &&
			sessionId &&
			navigationState.sessionId === sessionId &&
			navigationState.uploadStatus === AUTO_RUN_READY_UPLOAD_STATUS
	);
}

export function shouldStartUploadAutoRun({
	navigationState,
	sessionId,
	isRunningVerification,
	autoRunAttempt,
}) {
	if (!hasUploadAutoRunIntent({ navigationState, sessionId })) {
		return false;
	}

	if (isRunningVerification) {
		return false;
	}

	return !(
		autoRunAttempt?.sessionId === sessionId &&
		autoRunAttempt?.attempted === true
	);
}
