import { useEffect, useMemo, useState } from "react";
import {
	getSessionDocumentBlob,
	getVerificationWorkspace,
} from "../api/generalizedVerificationApi.js";

const REFRESH_INTERVAL_MS = 3000;
const TERMINAL_UI_STATUSES = new Set(["READY", "COMPLETED", "FAILED"]);

function normalizeWorkspacePayload(payload, sessionId) {
	const workspace = payload && typeof payload === "object" ? payload : {};
	const document = workspace.document || {};
	const summary = workspace.summary || {};
	const finalVerdict = workspace.final_verdict || {};

	return {
		sessionId: workspace.session_id || sessionId,
		status: workspace.status || "UNKNOWN",
		uiStatus: workspace.ui_status || "LOADING",
		document: {
			filename: document.filename || "",
			documentType: document.document_type || "unknown",
			pageCount: document.page_count ?? null,
			usedOcr: Boolean(document.used_ocr),
			warnings: Array.isArray(document.warnings) ? document.warnings : [],
			highlightsCount: Number(document.highlights_count || 0),
		},
		summary: {
			totalFields: Number(summary.total_fields || 0),
			greenCount: Number(summary.green_count || 0),
			amberCount: Number(summary.amber_count || 0),
			redCount: Number(summary.red_count || 0),
			matchingScore: Number(summary.matching_score || 0),
			visualMatchProbability: Number(summary.visual_match_probability || 0),
			riskLevel: summary.risk_level || "LOW",
			activeExceptions: Array.isArray(summary.active_exceptions)
				? summary.active_exceptions
				: [],
		},
		fields: Array.isArray(workspace.fields) ? workspace.fields : [],
		verifiers: Array.isArray(workspace.verifiers) ? workspace.verifiers : [],
		finalVerdict: {
			outcome: finalVerdict.outcome || workspace.status || "AMBER",
			reasonCodes: Array.isArray(finalVerdict.reason_codes)
				? finalVerdict.reason_codes
				: [],
			connectorIds: Array.isArray(finalVerdict.connector_ids)
				? finalVerdict.connector_ids
				: [],
			explanation: finalVerdict.explanation || "",
			riskLevel: finalVerdict.risk_level || summary.risk_level || "MEDIUM",
			matchingScore: Number(finalVerdict.matching_score || 0),
			visualMatchProbability: Number(finalVerdict.visual_match_probability || 0),
		},
		audit: Array.isArray(workspace.audit) ? workspace.audit : [],
		actions: Array.isArray(workspace.actions) ? workspace.actions : [],
		raw: workspace,
	};
}

function shouldPoll(workspace) {
	return workspace ? !TERMINAL_UI_STATUSES.has(workspace.uiStatus) : false;
}

export function useGeneralizedVerificationWorkspace({ sessionId, token }) {
	const [workspace, setWorkspace] = useState(null);
	const [documentUrl, setDocumentUrl] = useState("");
	const [error, setError] = useState("");
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		let isActive = true;
		let objectUrl = "";
		let timeoutId = null;

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

		async function loadWorkspace({ showLoading = false } = {}) {
			if (showLoading) {
				setIsLoading(true);
			}
			setError("");

			try {
				const payload = await getVerificationWorkspace(sessionId, token);
				if (!isActive) {
					return;
				}

				const normalizedWorkspace = normalizeWorkspacePayload(payload, sessionId);
				setWorkspace(normalizedWorkspace);
				setIsLoading(false);

				if (shouldPoll(normalizedWorkspace)) {
					timeoutId = window.setTimeout(() => {
						if (isActive) {
							loadWorkspace();
						}
					}, REFRESH_INTERVAL_MS);
				}
			} catch (requestError) {
				if (isActive) {
					setError(requestError.message);
					setIsLoading(false);
				}
			}
		}

		loadWorkspace({ showLoading: true });
		loadDocument();

		return () => {
			isActive = false;
			if (timeoutId) {
				window.clearTimeout(timeoutId);
			}
			if (objectUrl) {
				URL.revokeObjectURL(objectUrl);
			}
		};
	}, [sessionId, token]);

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
		error,
		warnings,
		documentUrl,
		workspace,
	};
}
