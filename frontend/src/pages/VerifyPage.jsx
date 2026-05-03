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

function getFieldValue(field) {
	return (
		field.value_preview ||
		field.valuePreview ||
		field.masked_value ||
		field.maskedValue ||
		"Hidden"
	);
}

function getFieldReason(field) {
	const reasons = asArray(field.reason_codes || field.reasonCodes);

	return reasons.length
		? reasons.join(", ")
		: field.reason_code || field.reasonCode || "";
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

	if (left > 100 || top > 100 || width > 100 || height > 100) {
		const PDF_BASE_WIDTH = 612;
		const PDF_BASE_HEIGHT = 792;

		left = (left / PDF_BASE_WIDTH) * 100;
		top = (top / PDF_BASE_HEIGHT) * 100;
		width = (width / PDF_BASE_WIDTH) * 100;
		height = (height / PDF_BASE_HEIGHT) * 100;
	}

	return {
		left: Math.max(0, Math.min(100, left)),
		top: Math.max(0, Math.min(100, top)),
		width: Math.max(1, Math.min(100, width)),
		height: Math.max(1, Math.min(100, height)),
	};
}

function getFieldBoxes(field) {
	return [
		...asArray(field.bounding_boxes),
		...asArray(field.boundingBoxes),
		...asArray(field.boxes),
		...asArray(field.geometry_boxes),
		...asArray(field.geometryBoxes),
		...(field.bounding_box ? [field.bounding_box] : []),
		...(field.boundingBox ? [field.boundingBox] : []),
		...(field.geometry ? [field.geometry] : []),
		...(field.box ? [field.box] : []),
	];
}

function buildHighlightItems(fields) {
	return fields.flatMap((field, fieldIndex) => {
		const fieldId = getFieldId(field, fieldIndex);
		const rawBoxes = getFieldBoxes(field);

		const status = normalizeStatus(field.status || field.outcome);
		const outcomeColor =
			status === "GREEN" ? "green" : status === "RED" ? "red" : "amber";

		return rawBoxes
			.map((box, boxIndex) => {
				const relativeBox = normalizeBoxToPercent(box || {});

				if (!relativeBox) {
					return null;
				}

				return {
					credentialId: fieldId,
					id: `${fieldId}-${boxIndex}`,
					label: getFieldLabel(field),
					documentValue: getFieldValue(field),
					explanation: getFieldExplanation(field),
					page: box.page || field.page || 1,
					auditStatus: status,
					outcomeColor,
					relativeBox,
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
			{fields.map((field, index) => {
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
							{field.provider_id || field.providerId
								? ` | Provider ${field.provider_id || field.providerId}`
								: ""}
						</p>

						{getFieldReason(field) ? (
							<p className="muted">Reason: {getFieldReason(field)}</p>
						) : null}

						<p className="muted">{getFieldExplanation(field)}</p>
					</button>
				);
			})}
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

function AuditReceiptPanel({ workspace }) {
	const audit = getAuditObject(workspace);
	const privacy = workspace?.privacy || {};

	const finalDecision =
		audit.final_decision ||
		audit.reviewer_decision ||
		audit.final_reviewer_decision ||
		"Pending";

	return (
		<div className="gv-card">
			<p className="eyebrow">Audit Receipt</p>

			<div className="gv-meta-stack">
				<span>
					<strong>Receipt ID:</strong>{" "}
					{formatValue(audit.audit_receipt_id || audit.receipt_id, "Pending")}
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
			(workspace.status === "PENDING_HUMAN_REVIEW" ||
				workspace.status === "HUMAN_APPROVED" ||
				workspace.status === "HUMAN_REJECTED" ||
				workspace.status === "MANUAL_REVIEW_REQUIRED" ||
				workspace.uiStatus === "READY" ||
				workspace.uiStatus === "COMPLETED" ||
				workspace.uiStatus === "Ready for human review")
	);

	const canCloseSession = Boolean(
		workspace &&
			(reviewCompleted ||
				workspace.status === "HUMAN_APPROVED" ||
				workspace.status === "HUMAN_REJECTED" ||
				workspace.status === "MANUAL_REVIEW_REQUIRED" ||
				workspace.status === "PENDING_CLEANUP" ||
				workspace.actionFlags?.can_close === true ||
				workspace.actions?.some(
					(action) => action.id === "can_close" && action.enabled !== false
				))
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

					<AuditReceiptPanel workspace={workspace} />

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
					<AuditReceiptPanel workspace={workspace} />

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
