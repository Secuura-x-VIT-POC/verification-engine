import React, { startTransition, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
	closeVerificationSession,
	runVerificationSession,
	submitReviewDecision,
} from "../features/generalized-verification/api/generalizedVerificationApi.js";
import DocumentTab from "../features/generalized-verification/components/DocumentTab";
import { useGeneralizedVerificationWorkspace } from "../features/generalized-verification/hooks/useGeneralizedVerificationWorkspace";
import "../features/generalized-verification/generalizedVerification.css";

const PAGE_ITEMS = [
	{ id: "overview", label: "Overview" },
	{ id: "document", label: "Document" },
	{ id: "analysis", label: "Analysis" },
	{ id: "audit", label: "Audit" },
];

const REVIEW_DECISIONS = [
	{
		decision: "APPROVE",
		label: "Approve Document",
		className: "primary-btn",
	},
	{
		decision: "REJECT",
		label: "Reject Document",
		className: "secondary-btn",
	},
	{
		decision: "NEEDS_MANUAL_REVIEW",
		label: "Needs Manual Review",
		className: "secondary-btn",
	},
];

function asArray(value) {
	return Array.isArray(value) ? value : [];
}

function isWorkspaceActionEnabled(actions, actionId) {
	return asArray(actions).some(
		(action) =>
			(action.id || action.action_id) === actionId &&
			action.enabled !== false
	);
}

function normalizeStatus(value, fallback = "AMBER") {
	const status = String(value || fallback).trim().toUpperCase();

	if (status.includes("MISMATCH") || status.includes("INVALID")) return "RED";
	if (status.includes("GREEN")) return "GREEN";
	if (status.includes("RED")) return "RED";
	if (status.includes("AMBER")) return "AMBER";
	if (status.includes("MATCH")) return "GREEN";

	return fallback;
}

function VerdictBadge({ outcome }) {
	const normalized = normalizeStatus(outcome, "PENDING");

	if (normalized === "GREEN") {
		return <span className="badge badge-green">GREEN</span>;
	}

	if (normalized === "RED") {
		return <span className="badge badge-red">RED</span>;
	}

	if (normalized === "AMBER") {
		return <span className="badge badge-amber">AMBER</span>;
	}

	return <span className="gv-status-badge gv-status-neutral">Pending</span>;
}

function formatPercent(value) {
	const numberValue = Number(value);

	if (!Number.isFinite(numberValue)) {
		return "N/A";
	}

	return `${Math.round(numberValue * 100)}%`;
}

function formatValue(value, fallback = "N/A") {
	if (value === null || value === undefined || value === "") {
		return fallback;
	}

	if (typeof value === "boolean") {
		return value ? "Yes" : "No";
	}

	return String(value);
}

function getFieldId(field, index) {
	return (
		field.field_id ||
		field.fieldId ||
		field.id ||
		`${field.label || "field"}-${index}`
	);
}

function getFieldLabel(field) {
	return (
		field.label ||
		field.field_label ||
		field.name ||
		field.field_id ||
		"Unknown field"
	);
}

function isMaskedDisplayValue(value) {
	const text = String(value || "").trim();
	if (!text) return false;

	return (
		text === "***" ||
		text.includes("***") ||
		/^\*+$/.test(text) ||
		/\*{2,}/.test(text)
	);
}

function getFieldValue(field) {
	const value =
		field.value_preview ||
		field.valuePreview ||
		field.masked_value ||
		field.maskedValue ||
		field.extracted_value ||
		field.extractedValue ||
		field.normalized_value ||
		field.normalizedValue ||
		"Hidden";

	if (isMaskedDisplayValue(value)) {
		return "Masked value — hidden by privacy policy";
	}

	return value;
}

function getFieldReason(field) {
	const reasons = asArray(field.reason_codes || field.reasonCodes);

	return reasons.length
		? reasons.join(", ")
		: field.reason_code || field.reasonCode || "";
}

function getFieldGroupKey(field) {
	return [
		field.importance || "important",
		field.verification_intent || field.verificationIntent || "manual_review",
		normalizeStatus(field.status || field.outcome),
		`page ${field.page_number || field.pageNumber || field.page || 1}`,
	].join(" | ");
}

function getFieldExplanation(field) {
	return (
		field.audit_message ||
		field.auditMessage ||
		field.explanation ||
		"No explanation available."
	);
}

function getFieldConfidence(field) {
	return (
		field.final_confidence ??
		field.finalConfidence ??
		field.confidence ??
		field.ai_confidence
	);
}

function getAuditObject(workspace) {
	if (
		workspace?.auditReceipt &&
		typeof workspace.auditReceipt === "object" &&
		!Array.isArray(workspace.auditReceipt)
	) {
		return workspace.auditReceipt;
	}

	return {};
}

function normalizeBoxToPercent(box) {
	const coordinateSpace = box.coordinate_space || box.coordinateSpace;
	if (coordinateSpace === "pp_chatocr_image_pixels") {
		return null;
	}
	const rawX0 = box.x0 ?? box.left ?? box.x ?? 0;
	const rawY0 = box.y0 ?? box.top ?? box.y ?? 0;
	const rawX1 = box.x1;
	const rawY1 = box.y1;

	let left = Number(rawX0);
	let top = Number(rawY0);

	let width =
		box.width !== undefined
			? Number(box.width)
			: rawX1 !== undefined
				? Number(rawX1) - left
				: null;

	let height =
		box.height !== undefined
			? Number(box.height)
			: rawY1 !== undefined
				? Number(rawY1) - top
				: null;

	if (![left, top, width, height].every(Number.isFinite)) {
		return null;
	}

	if (width <= 0 || height <= 0) {
		return null;
	}

	if (left > 100 || top > 100 || width > 100 || height > 100) return null;

	return {
		left: Math.max(0, Math.min(100, left)),
		top: Math.max(0, Math.min(100, top)),
		width: Math.max(1, Math.min(100, width)),
		height: Math.max(1, Math.min(100, height)),
	};
}

function normalizeAbsoluteBox(box) {
	const rawBox = Array.isArray(box.bbox) ? box.bbox : null;
	const rawX0 = rawBox ? rawBox[0] : box.x0 ?? box.left ?? box.x ?? 0;
	const rawY0 = rawBox ? rawBox[1] : box.y0 ?? box.top ?? box.y ?? 0;
	const rawX1 = rawBox ? rawBox[2] : box.x1;
	const rawY1 = rawBox ? rawBox[3] : box.y1;
	const left = Number(rawX0);
	const top = Number(rawY0);
	const width =
		box.width !== undefined
			? Number(box.width)
			: rawX1 !== undefined
				? Number(rawX1) - left
				: null;
	const height =
		box.height !== undefined
			? Number(box.height)
			: rawY1 !== undefined
				? Number(rawY1) - top
				: null;

	if (![left, top, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
		return null;
	}

	return { left, top, width, height };
}

function boxFromPolygon(polygon) {
	const points = asArray(polygon).filter((point) => Array.isArray(point) && point.length >= 2);
	if (!points.length) return null;
	const xValues = points.map((point) => Number(point[0])).filter(Number.isFinite);
	const yValues = points.map((point) => Number(point[1])).filter(Number.isFinite);
	if (!xValues.length || !yValues.length) return null;
	const x0 = Math.min(...xValues);
	const y0 = Math.min(...yValues);
	const x1 = Math.max(...xValues);
	const y1 = Math.max(...yValues);
	return { x0, y0, x1, y1, bbox: [x0, y0, x1, y1], polygon };
}

function asNonEmptyArray(value) {
	return Array.isArray(value) && value.length ? value : null;
}

function getCanonicalFieldBoxes(field) {
	const canonical =
		asNonEmptyArray(field.bounding_boxes) ||
		asNonEmptyArray(field.boundingBoxes);

	if (canonical) return canonical;

	const legacy =
		asNonEmptyArray(field.boxes) ||
		asNonEmptyArray(field.geometry_boxes) ||
		asNonEmptyArray(field.geometryBoxes);

	if (legacy) return legacy;

	if (field.bounding_box) return [field.bounding_box];
	if (field.boundingBox) return [field.boundingBox];
	if (field.bbox) return [{ bbox: field.bbox }];
	if (field.geometry) return [field.geometry];
	if (field.box) return [field.box];

	if (field.polygon) {
		const polygonBox = boxFromPolygon(field.polygon);
		return polygonBox ? [polygonBox] : [];
	}

	return [];
}

function roundBoxValue(value) {
	const numberValue = Number(value);
	if (!Number.isFinite(numberValue)) return "0";
	return numberValue.toFixed(2);
}

function buildHighlightDedupeKey(page, relativeBox, absoluteBox) {
	const box = relativeBox || absoluteBox;
	if (!box) return null;

	return [
		page,
		roundBoxValue(box.left),
		roundBoxValue(box.top),
		roundBoxValue(box.width),
		roundBoxValue(box.height),
	].join(":");
}

function buildHighlightItems(fields) {
	const seenBoxes = new Set();

	return fields.flatMap((field, fieldIndex) => {
		const fieldId = getFieldId(field, fieldIndex);
		const rawBoxes = getCanonicalFieldBoxes(field);

		const status = normalizeStatus(field.status || field.outcome);
		const outcomeColor =
			status === "GREEN" ? "green" : status === "RED" ? "red" : "amber";

		return rawBoxes
			.map((box, boxIndex) => {
				const enrichedBox = {
					...box,
					page:
						box.page ||
						field.page ||
						field.page_number ||
						field.pageNumber ||
						1,
					page_number:
						box.page_number ||
						box.pageNumber ||
						field.page_number ||
						field.pageNumber ||
						box.page ||
						field.page ||
						1,
					coordinate_space:
						box.coordinate_space ||
						box.coordinateSpace ||
						field.coordinate_space ||
						field.coordinateSpace,
					source_width:
						box.source_width ||
						box.sourceWidth ||
						field.source_width ||
						field.sourceWidth,
					source_height:
						box.source_height ||
						box.sourceHeight ||
						field.source_height ||
						field.sourceHeight,
				};

				const relativeBox = normalizeBoxToPercent(enrichedBox);
				const absoluteBox = normalizeAbsoluteBox(enrichedBox);

				if (!relativeBox && !absoluteBox) {
					return null;
				}

				const page =
					enrichedBox.page_number ||
					enrichedBox.pageNumber ||
					enrichedBox.page ||
					1;

				const dedupeKey = buildHighlightDedupeKey(
					page,
					relativeBox,
					absoluteBox
				);

				if (!dedupeKey || seenBoxes.has(dedupeKey)) {
					return null;
				}

				seenBoxes.add(dedupeKey);

				return {
					credentialId: fieldId,
					id: `${fieldId}-${dedupeKey}-${boxIndex}`,
					label: getFieldLabel(field),
					documentValue: getFieldValue(field),
					explanation: getFieldExplanation(field),
					page,
					auditStatus: status,
					outcomeColor,
					relativeBox,
					absoluteBox,
					polygon: enrichedBox.polygon,
					coordinateSpace:
						enrichedBox.coordinate_space || enrichedBox.coordinateSpace,
					sourceWidth: enrichedBox.source_width || enrichedBox.sourceWidth,
					sourceHeight: enrichedBox.source_height || enrichedBox.sourceHeight,
				};
			})
			.filter(Boolean);
	});
}

function FieldList({ fields, activeFieldId, onSelectField }) {
	if (!fields.length) {
		return <p className="muted">No fields were returned by the workspace graph.</p>;
	}

	return (
		<div className="field-list">
			{Object.entries(fields.reduce((groups, field) => {
				const key = getFieldGroupKey(field);
				groups[key] = groups[key] || [];
				groups[key].push(field);
				return groups;
			}, {})).map(([groupLabel, groupFields]) => (
				<div key={groupLabel} className="gv-field-group">
					<p className="eyebrow">{groupLabel}</p>
					{groupFields.map((field, index) => {
				const fieldId = getFieldId(field, index);
				const status = normalizeStatus(field.status || field.outcome);
				const confidence = getFieldConfidence(field);
				const isActive = activeFieldId === fieldId;

				return (
					<button
						key={fieldId}
						type="button"
						className={`field-row ${isActive ? "is-active" : ""}`}
						onClick={() => onSelectField(fieldId)}
						onMouseEnter={() => onSelectField(fieldId)}
					>
						<div className="action-row">
							<p>
								<strong>{getFieldLabel(field)}:</strong> {getFieldValue(field)}
							</p>
							<VerdictBadge outcome={status} />
						</div>

						<p className="muted">
							Confidence {formatPercent(confidence)}
							{field.verification_intent || field.verificationIntent
								? ` | Intent ${field.verification_intent || field.verificationIntent}`
								: ""}
							{field.data_type || field.dataType
								? ` | Type ${field.data_type || field.dataType}`
								: ""}
							{field.provider_id || field.providerId
								? ` | Provider ${field.provider_id || field.providerId}`
								: ""}
						</p>
						{field.normalized_value || field.normalizedValue ? (
							<p className="muted">
								Normalized: {field.normalized_value || field.normalizedValue}
							</p>
						) : null}

						{getFieldReason(field) ? (
							<p className="muted">Reason: {getFieldReason(field)}</p>
						) : null}

						<p className="muted">{getFieldExplanation(field)}</p>
					</button>
				);
					})}
				</div>
			))}
		</div>
	);
}

function VerifierList({ verifiers }) {
	if (!verifiers.length) {
		return <p className="muted">No external verifier was required for this workspace.</p>;
	}

	return (
		<div className="field-list">
			{verifiers.map((verifier, index) => {
				const providerId =
					verifier.provider_id ||
					verifier.providerId ||
					verifier.connector_id ||
					verifier.connectorId ||
					`verifier-${index + 1}`;

				const checkedFields = asArray(
					verifier.field_ids || verifier.fieldIds
				).join(", ");

				const reason = asArray(
					verifier.reason_codes || verifier.reasonCodes
				).join(", ");

				return (
					<div key={`${providerId}-${index}`} className="field-row">
						<div className="action-row">
							<p>
								<strong>{providerId}</strong>{" "}
								{formatValue(verifier.status || verifier.result, "Pending")}
							</p>
							<VerdictBadge
								outcome={verifier.status || verifier.outcome || verifier.result}
							/>
						</div>

						<p className="muted">
							Confidence {formatPercent(verifier.confidence)} |{" "}
							{verifier.high_assurance || verifier.highAssurance
								? "High assurance"
								: "Standard assurance"}
						</p>

						{checkedFields ? <p className="muted">Fields: {checkedFields}</p> : null}
						{reason ? <p className="muted">Reason: {reason}</p> : null}
					</div>
				);
			})}
		</div>
	);
}

function AuditList({ audit }) {
	if (!audit.length) {
		return <p className="muted">No audit entries are available yet.</p>;
	}

	return (
		<div className="field-list">
			{audit.map((entry, index) => (
				<div
					key={`${entry.stage || "audit"}-${entry.timestamp || index}`}
					className="field-row"
				>
					<p>
						<strong>{entry.stage || "Audit"}</strong> {entry.level || "INFO"}
					</p>
					<p>{entry.message || entry.audit_message || "Audit entry recorded."}</p>
					{entry.timestamp ? <p className="muted">{entry.timestamp}</p> : null}
				</div>
			))}
		</div>
	);
}

function AuditReceiptPanel({ workspace, reviewResult }) {
	const audit = getAuditObject(workspace);
	const privacy = workspace?.privacy || {};

	const finalDecision =
		reviewResult?.finalDecision ||
		audit.final_decision ||
		audit.reviewer_decision ||
		audit.final_reviewer_decision ||
		"Pending";

	const receiptId =
		reviewResult?.auditReceiptId ||
		audit.audit_receipt_id ||
		audit.receipt_id;

	return (
		<div className="gv-card">
			<p className="eyebrow">Audit Receipt</p>

			<div className="gv-meta-stack">
				<span>
					<strong>Receipt ID:</strong>{" "}
					{formatValue(receiptId, "Pending")}
				</span>

				<span>
					<strong>Document commitment:</strong>{" "}
					{formatValue(
						audit.document_commitment || audit.document_hash,
						"Pending"
					)}
				</span>

				<span>
					<strong>Final decision:</strong> {formatValue(finalDecision, "Pending")}
				</span>

				<span>
					<strong>Issued at:</strong>{" "}
					{formatValue(
						audit.issued_at || audit.approved_at || audit.rejected_at,
						"Pending"
					)}
				</span>

				<span>
					<strong>Raw text persisted:</strong>{" "}
					{formatValue(privacy.raw_text_persisted ?? false)}
				</span>

				<span>
					<strong>PII persisted:</strong>{" "}
					{formatValue(privacy.pii_persisted ?? false)}
				</span>
			</div>
		</div>
	);
}

function OverviewCard({ title, children, className = "" }) {
	return (
		<div className={`gv-card ${className}`}>
			<p className="eyebrow">{title}</p>
			{children}
		</div>
	);
}

export default function VerifyPage({ auth, onLogout }) {
	const { sessionId } = useParams();
	const navigate = useNavigate();

	const [activePage, setActivePage] = useState("overview");
	const [activeFieldId, setActiveFieldId] = useState("");
	const [reviewerNote, setReviewerNote] = useState("");
	const [reviewMessage, setReviewMessage] = useState("");
	const [reviewError, setReviewError] = useState("");
	const [closeError, setCloseError] = useState("");
	const [isClosing, setIsClosing] = useState(false);
	const [isSubmittingReview, setIsSubmittingReview] = useState(false);
	const [isRunningVerification, setIsRunningVerification] = useState(false);
	const [reviewCompleted, setReviewCompleted] = useState(false);
	const [reviewResult, setReviewResult] = useState(null);

	const {
		documentUrl,
		error,
		hydrateWorkspace,
		isLoading,
		isWorkspacePending,
		refreshWorkspace,
		warnings,
		workspace,
	} =
		useGeneralizedVerificationWorkspace({
			sessionId,
			token: auth.token,
		});

	const summaryStats = useMemo(() => {
		if (!workspace) return [];

		return [
			{ label: "Fields", value: workspace.summary.totalFields },
			{ label: "Green", value: workspace.summary.greenCount },
			{ label: "Amber", value: workspace.summary.amberCount },
			{ label: "Red", value: workspace.summary.redCount },
			{ label: "Risk", value: workspace.summary.riskLevel },
			{ label: "Match", value: formatPercent(workspace.summary.matchingScore) },
		];
	}, [workspace]);

	const highlightItems = useMemo(
		() => buildHighlightItems(workspace?.fields || []),
		[workspace]
	);

	const canReview = Boolean(
		workspace &&
			workspace.status === "PENDING_HUMAN_REVIEW" &&
			!reviewCompleted
	);

	const FINAL_REVIEW_STATUSES = new Set([
	"HUMAN_APPROVED",
	"HUMAN_REJECTED",
	"MANUAL_REVIEW_REQUIRED",
	"PENDING_CLEANUP",
]);

const canCloseSession = Boolean(
	workspace &&
		(FINAL_REVIEW_STATUSES.has(workspace.status) ||
			workspace.actionFlags?.can_close === true ||
			isWorkspaceActionEnabled(workspace.actions, "can_close"))
);

	async function handleRunVerification() {
		setReviewError("");
		setCloseError("");
		setReviewMessage("");
		setIsRunningVerification(true);

		try {
			const workspacePayload = await runVerificationSession(sessionId, auth.token);

			if (workspacePayload) {
				hydrateWorkspace(workspacePayload);
				setReviewMessage("Verification completed. Workspace is ready for review.");
			} else {
				await refreshWorkspace({ retryOnPending: true });
				setReviewMessage("Verification completed. Workspace refresh requested.");
			}
		} catch (requestError) {
			setReviewError(
				requestError.message ||
					"Unable to refresh verification. The session may already be processing."
			);
		} finally {
			setIsRunningVerification(false);
		}
	}

	async function handleReviewDecision(decision) {
		setReviewError("");
		setReviewMessage("");
		setCloseError("");

		if (decision === "NEEDS_MANUAL_REVIEW" && !reviewerNote.trim()) {
			setReviewError("Please add a reviewer note before marking manual review.");
			return;
		}

		setIsSubmittingReview(true);

		try {
			const reviewResponse = await submitReviewDecision(
				sessionId,
				auth.token,
				decision,
				reviewerNote.trim()
			);

			setReviewCompleted(true);

			setReviewResult({
				status: reviewResponse?.status,
				finalDecision:
					reviewResponse?.final_decision ||
					reviewResponse?.reviewer_decision ||
					decision,
				auditReceiptId: reviewResponse?.audit_receipt_id,
			});

			await refreshWorkspace({ showLoading: false });

			setReviewMessage(
				`Review decision submitted successfully: ${
					reviewResponse?.final_decision ||
					reviewResponse?.reviewer_decision ||
					decision
				}. You can now close the session.`
			);
		} catch (requestError) {
			setReviewError(requestError.message || "Unable to submit review decision.");
		} finally {
			setIsSubmittingReview(false);
		}
	}

	async function handleCloseSession() {
		setCloseError("");
		setReviewError("");
		setIsClosing(true);

		try {
			await closeVerificationSession(sessionId, auth.token);
			startTransition(() => navigate("/upload"));
		} catch (requestError) {
			setCloseError(requestError.message || "Unable to close session.");
		} finally {
			setIsClosing(false);
		}
	}

	function renderOverviewPage() {
		if (!workspace) return null;

		return (
			<div className="gv-page-content">
				<div className="gv-overview-grid">
					<OverviewCard title="Verdict">
						<div className="gv-meta-stack">
							<span>
								<strong>Status:</strong> {workspace.status}
							</span>
							<span>
								<strong>UI:</strong> {workspace.uiStatus}
							</span>
							<span>
								<strong>Outcome:</strong>{" "}
								<VerdictBadge outcome={workspace.finalVerdict.outcome} />
							</span>
							<span>
								<strong>Risk:</strong> {workspace.finalVerdict.riskLevel}
							</span>
						</div>
					</OverviewCard>

					<OverviewCard title="Document">
						<div className="gv-meta-stack">
							<span>
								<strong>File:</strong> {workspace.document.filename || "N/A"}
							</span>
							<span>
								<strong>Type:</strong> {workspace.document.documentType}
							</span>
							<span>
								<strong>Pages:</strong> {workspace.document.pageCount || "N/A"}
							</span>
							<span>
								<strong>OCR:</strong> {workspace.document.usedOcr ? "Yes" : "No"}
							</span>
						</div>
					</OverviewCard>

					<OverviewCard title="Summary">
						<div className="gv-stat-grid">
							{summaryStats.map((stat) => (
								<div key={stat.label} className="gv-stat-card">
									<span className="gv-stat-value">{stat.value}</span>
									<span className="gv-stat-label">{stat.label}</span>
								</div>
							))}
						</div>
					</OverviewCard>

					<OverviewCard title="Human Review" className="gv-card-wide">
						<textarea
							value={reviewerNote}
							onChange={(event) => setReviewerNote(event.target.value)}
							placeholder="Reviewer note, required for manual review"
							rows={4}
							className="gv-textarea"
						/>

						<div className="gv-button-stack">
							{REVIEW_DECISIONS.map((action) => (
								<button
									key={action.decision}
									type="button"
									className={action.className}
									onClick={() => handleReviewDecision(action.decision)}
									disabled={!canReview || isSubmittingReview}
								>
									{isSubmittingReview ? "Submitting..." : action.label}
								</button>
							))}
						</div>

						<p className="muted">
							Review actions unlock when verification findings are ready.
						</p>
					</OverviewCard>

					<OverviewCard title="Session Actions">
						<div className="gv-button-stack">
							<button
								type="button"
								className="secondary-btn"
								onClick={handleRunVerification}
								disabled={isRunningVerification}
							>
								{isRunningVerification
									? "Refreshing..."
									: "Refresh Verification State"}
							</button>

							<button
								type="button"
								className="primary-btn"
								onClick={handleCloseSession}
								disabled={!canCloseSession || isClosing}
							>
								{isClosing ? "Closing..." : "Close Session"}
							</button>
						</div>

						{canCloseSession ? (
							<p className="muted">
								Review decision is complete. You can close this session now.
							</p>
						) : (
							<p className="muted">
								Submit a review decision before closing this session.
							</p>
						)}
					</OverviewCard>

					<AuditReceiptPanel workspace={workspace} reviewResult={reviewResult} />

					<OverviewCard title="Notices" className="gv-card-wide">
						{warnings.length ? (
							<div className="gv-warning-list">
								{warnings.map((warning) => (
									<p key={warning} className="muted">
										{warning}
									</p>
								))}
							</div>
						) : (
							<p className="muted">No notices for this session.</p>
						)}
					</OverviewCard>
				</div>
			</div>
		);
	}

	function renderDocumentPage() {
		return (
			<div className="gv-page-content">
				<div className="gv-section-heading">
					<p className="eyebrow">Document</p>
					<h2>Session document and PDF highlights</h2>
				</div>

				<DocumentTab
					documentUrl={documentUrl}
					documentMessage={
						documentUrl ? null : "No PDF is currently stored for this session."
					}
					highlightItems={highlightItems}
					selectedCredentialId={activeFieldId}
					onSelectCredential={setActiveFieldId}
				/>
			</div>
		);
	}

	function renderAnalysisPage() {
		if (!workspace) return null;

		return (
			<div className="gv-page-content">
				<div className="gv-section-heading">
					<p className="eyebrow">Analysis</p>
					<h2>Field findings and verifier results</h2>
				</div>

				<div className="gv-stack">
					<div className="gv-card">
						<p className="eyebrow">Findings</p>
						<FieldList
							fields={workspace.fields}
							activeFieldId={activeFieldId}
							onSelectField={setActiveFieldId}
						/>
					</div>

					<div className="gv-card">
						<p className="eyebrow">Verifier Results</p>
						<VerifierList verifiers={workspace.verifiers} />
					</div>
				</div>
			</div>
		);
	}

	function renderAuditPage() {
		if (!workspace) return null;

		return (
			<div className="gv-page-content">
				<div className="gv-section-heading">
					<p className="eyebrow">Audit</p>
					<h2>Audit receipt and trail</h2>
				</div>

				<div className="gv-stack">
					<AuditReceiptPanel workspace={workspace} reviewResult={reviewResult} />

					<div className="gv-card">
						<p className="eyebrow">Audit Trail</p>
						<AuditList audit={workspace.audit} />
					</div>
				</div>
			</div>
		);
	}

	function renderActivePage() {
		switch (activePage) {
			case "document":
				return renderDocumentPage();
			case "analysis":
				return renderAnalysisPage();
			case "audit":
				return renderAuditPage();
			case "overview":
			default:
				return renderOverviewPage();
		}
	}

	return (
		<div className="page gv-page">
			<div className="app-header">
				<div>
					<p className="eyebrow">Verification workspace</p>
					<h1>Session {workspace?.sessionId || sessionId}</h1>
					<p className="muted">Signed in as {auth.username}</p>
				</div>

				<div className="header-actions">
					<button
						type="button"
						className="secondary-btn"
						onClick={() => startTransition(() => navigate("/upload"))}
					>
						New Upload
					</button>

					<button type="button" className="secondary-btn" onClick={onLogout}>
						Logout
					</button>
				</div>
			</div>

			{isLoading ? <p className="muted">Loading verification workspace...</p> : null}
			{isWorkspacePending && !workspace && !isLoading ? (
				<div className="gv-pending-panel">
					<div className="gv-pending-icon" aria-hidden="true">⏳</div>
					<p className="gv-pending-title">Workspace is not ready yet.</p>
					<p className="muted">
						Run verification to generate the review workspace.
					</p>
					<button
						id="run-verification-btn"
						type="button"
						className="primary-btn"
						onClick={handleRunVerification}
						disabled={isRunningVerification}
					>
						{isRunningVerification ? "Running verification..." : "Run Verification"}
					</button>
					{reviewError ? (
						<p className="error-text gv-pending-error">{reviewError}</p>
					) : null}
				</div>
			) : null}
			{error ? <p className="error-text">{error}</p> : null}
			{closeError ? <p className="error-text">{closeError}</p> : null}
			{workspace && reviewError ? <p className="error-text">{reviewError}</p> : null}
			{reviewMessage ? <p className="success-text">{reviewMessage}</p> : null}

			{workspace ? (
				<div className="gv-shell">
					<aside className="gv-side-nav">
						<div className="gv-side-nav-inner">
							<p className="eyebrow">Workspace</p>

							{PAGE_ITEMS.map((item) => (
								<button
									key={item.id}
									type="button"
									className={`gv-side-nav-button ${
										activePage === item.id ? "is-active" : ""
									}`}
									onClick={() => setActivePage(item.id)}
								>
									{item.label}
								</button>
							))}
						</div>
					</aside>

					<main className="gv-main-panel">
						<div className="gv-hero-card">
							<p className="eyebrow">Final Verdict</p>
							<h2>
								{workspace.finalVerdict.explanation ||
									"Workspace graph completed."}
							</h2>

							{workspace.finalVerdict.reasonCodes.length ? (
								<p className="muted">
									{workspace.finalVerdict.reasonCodes.join(", ")}
								</p>
							) : null}
						</div>

						{renderActivePage()}
					</main>
				</div>
			) : null}
		</div>
	);
}
