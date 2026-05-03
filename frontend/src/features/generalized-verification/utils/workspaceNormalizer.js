const UNSAFE_WORKSPACE_KEYS = new Set([
	"raw_text",
	"raw_ocr_text",
	"raw_pdf_text",
	"pdf_text",
	"full_pdf_text",
	"full_ocr_text",
	"ocr_text",
	"source_text",
	"document_value",
	"raw_value",
	"spatial_text_map",
	"evidence_lines",
	"field_candidates",
	"generalized_analysis",
	"agent_private_notes",
	"agent_raw_output",
	"agent_document_understanding_payload",
	"agent_credential_candidates_payload",
	"agent_route_recommendations_payload",
	"agent_explanations_payload",
	"verifier_raw_evidence",
	"verifier_raw_response",
	"raw_verifier_response",
	"provider_raw_response",
	"raw_provider_body",
	"provider_raw_body",
	"raw_connector_response",
	"full_provider_response",
	"raw_result_summary",
	"raw_response",
	"raw_payload",
	"input_payload",
	"evidence_payload",
	"request_body",
	"response_body",
	"verifier_request_body",
	"verifier_response_body",
	"full_gemini_prompt",
	"raw_gemini_prompt",
	"full_prompt",
	"gemini_prompt",
	"full_gemini_response",
	"raw_gemini_response",
	"full_response",
	"gemini_response",
	"gemini_raw_response",
	"reviewer_note",
	"private_reasoning",
	"raw_reviewer_note",
	"connector_payload",
	"provider_execution_traces_payload",
]);

function asSafeObject(value) {
	return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asSafeArray(value) {
	return Array.isArray(value) ? value : [];
}

function sanitizeWorkspaceValue(value) {
	if (Array.isArray(value)) {
		return value.map((item) => sanitizeWorkspaceValue(item));
	}

	if (value && typeof value === "object") {
		return Object.fromEntries(
			Object.entries(value)
				.filter(([key]) => !UNSAFE_WORKSPACE_KEYS.has(key))
				.map(([key, nestedValue]) => [key, sanitizeWorkspaceValue(nestedValue)])
		);
	}

	return value;
}

export function normalizeWorkspacePayload(payload, sessionId) {
	const workspace = sanitizeWorkspaceValue(asSafeObject(payload));
	const document = asSafeObject(workspace.document);
	const summary = asSafeObject(workspace.summary);
	const finalVerdict = asSafeObject(
		workspace.final_verdict || workspace.finalVerdict
	);
	const auditReceipt = asSafeObject(
		workspace.audit_receipt ||
			workspace.auditReceipt ||
			workspace.audit_summary ||
			workspace.audit
	);

	return {
		sessionId: workspace.session_id || sessionId,
		status: workspace.status || "UNKNOWN",
		uiStatus: workspace.ui_status || "LOADING",

		document: {
			filename: document.filename || "",
			documentType: document.document_type || "unknown",
			pageCount: document.page_count ?? null,
			usedOcr: Boolean(document.used_ocr),
			warnings: asSafeArray(document.warnings),
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
			activeExceptions: asSafeArray(summary.active_exceptions),
		},

		fields: asSafeArray(workspace.fields || workspace.findings),
		verifiers: asSafeArray(workspace.verifiers || workspace.verification_tasks),

		finalVerdict: {
			outcome: finalVerdict.outcome || workspace.status || "AMBER",
			reasonCodes: asSafeArray(
				finalVerdict.reason_codes || finalVerdict.reasonCodes
			),
			connectorIds: asSafeArray(
				finalVerdict.connector_ids || finalVerdict.connectorIds
			),
			explanation: finalVerdict.explanation || "",
			riskLevel: finalVerdict.risk_level || summary.risk_level || "MEDIUM",
			matchingScore: Number(finalVerdict.matching_score || 0),
			visualMatchProbability: Number(
				finalVerdict.visual_match_probability || 0
			),
		},

		audit: asSafeArray(workspace.audit || workspace.audit_summary),
		auditReceipt,

		actions: asSafeArray(workspace.actions),
		actionFlags: workspace.action_flags || workspace.actionFlags || {},
		privacy: workspace.privacy || {},
	};
}
