const FALLBACK_NOTICE_MESSAGES = {
	SCHEMA_INFERENCE_FAILED:
		"AI schema inference could not complete, so the system used a deterministic fallback.",
	DETERMINISTIC_OCR_LABEL_VALUE_FALLBACK:
		"Deterministic OCR label-value extraction was used to continue processing.",
};

const MANUAL_REVIEW_NOTICE_MESSAGES = {
	MANUAL_REVIEW_PROVIDER_SELECTED:
		"Automated provider verification was unavailable or inconclusive for this claim.",
	MANUAL_REVIEW_REQUIRED:
		"This document requires human review before final approval.",
};

const FALLBACK_NOTICE_CODES = new Set(Object.keys(FALLBACK_NOTICE_MESSAGES));
const MANUAL_REVIEW_NOTICE_CODES = new Set(
	Object.keys(MANUAL_REVIEW_NOTICE_MESSAGES)
);

export const PROCESSING_WORKFLOW_STATUSES = new Set(["VERIFYING"]);

export const FAILED_WORKFLOW_STATUSES = new Set([
	"FAILED",
	"FAILED_RETRIABLE",
	"ABANDONED_VERIFYING",
	"FAILED_PURGED",
]);

function asArray(value) {
	return Array.isArray(value) ? value : [];
}

function normalizeCode(value) {
	const code = String(value || "").trim().toUpperCase();
	return code || null;
}

function collectReasonCodesFromItems(items) {
	return asArray(items).flatMap((item) =>
		asArray(item?.reason_codes || item?.reasonCodes)
	);
}

export function classifyVerificationNotice(code) {
	const normalizedCode = normalizeCode(code);

	if (!normalizedCode) {
		return null;
	}

	if (FALLBACK_NOTICE_CODES.has(normalizedCode)) {
		return {
			code: normalizedCode,
			type: "fallback",
			message: FALLBACK_NOTICE_MESSAGES[normalizedCode],
			fatal: false,
		};
	}

	if (MANUAL_REVIEW_NOTICE_CODES.has(normalizedCode)) {
		return {
			code: normalizedCode,
			type: "manual_review",
			message: MANUAL_REVIEW_NOTICE_MESSAGES[normalizedCode],
			fatal: false,
		};
	}

	return {
		code: normalizedCode,
		type: "notice",
		message: normalizedCode,
		fatal: false,
	};
}

export function buildVerificationNotices(workspace) {
	if (!workspace) {
		return [];
	}

	const codes = [
		...asArray(workspace.document?.warnings),
		...asArray(workspace.summary?.activeExceptions),
		...asArray(workspace.finalVerdict?.reasonCodes),
		...collectReasonCodesFromItems(workspace.fields),
		...collectReasonCodesFromItems(workspace.verifiers),
		...collectReasonCodesFromItems(workspace.audit),
	];

	const notices = [];
	const seen = new Set();

	for (const code of codes) {
		const notice = classifyVerificationNotice(code);
		if (!notice || seen.has(notice.code)) {
			continue;
		}
		seen.add(notice.code);
		notices.push(notice);
	}

	return notices;
}

export function isWorkspaceProcessing(workspace) {
	const status = normalizeCode(workspace?.status);
	return PROCESSING_WORKFLOW_STATUSES.has(status);
}

export function isWorkspaceFailed(workspace) {
	const status = normalizeCode(workspace?.status);
	return FAILED_WORKFLOW_STATUSES.has(status);
}
