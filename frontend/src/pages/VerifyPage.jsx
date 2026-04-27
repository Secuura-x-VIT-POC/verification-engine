import React, { startTransition, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiRequest } from "../lib/api";
import DocumentTab from "../features/generalized-verification/components/DocumentTab";
import WorkspaceTabNav from "../features/generalized-verification/components/WorkspaceTabNav";
import { useGeneralizedVerificationWorkspace } from "../features/generalized-verification/hooks/useGeneralizedVerificationWorkspace";
import "../features/generalized-verification/generalizedVerification.css";

function VerdictBadge({ outcome }) {
	if (outcome === "GREEN") {
		return <span className="badge badge-green">GREEN</span>;
	}
	if (outcome === "RED") {
		return <span className="badge badge-red">RED</span>;
	}
	if (outcome === "AMBER") {
		return <span className="badge badge-amber">AMBER</span>;
	}
	return <span className="gv-status-badge gv-status-neutral">Pending</span>;
}

function formatPercent(value) {
	return `${Math.round(Number(value || 0) * 100)}%`;
}

function FieldList({ fields }) {
	if (!fields.length) {
		return <p className="muted">No fields were returned by the workspace graph.</p>;
	}

	return (
		<div className="field-list">
			{fields.map((field) => (
				<div key={field.field_id} className="field-row">
					<div className="action-row">
						<p>
							<strong>{field.label || field.field_id}:</strong>{" "}
							{field.extracted_value || "Not extracted"}
						</p>
						<VerdictBadge outcome={field.status} />
					</div>
					<p className="muted">
						Confidence {formatPercent(field.final_confidence)} | AI{" "}
						{formatPercent(field.ai_confidence)} | Grounding{" "}
						{formatPercent(field.grounding_confidence)}
					</p>
					{field.reason_codes?.length ? (
						<p className="muted">{field.reason_codes.join(", ")}</p>
					) : null}
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
			{verifiers.map((verifier) => (
				<div key={`${verifier.connector_id}-${verifier.field_ids?.join("-")}`} className="field-row">
					<p>
						<strong>{verifier.connector_id}</strong> {verifier.status}
					</p>
					<p className="muted">
						Confidence {formatPercent(verifier.confidence)} |{" "}
						{verifier.high_assurance ? "High assurance" : "Optional"}
					</p>
					{verifier.reason_codes?.length ? (
						<p className="muted">{verifier.reason_codes.join(", ")}</p>
					) : null}
				</div>
			))}
		</div>
	);
}

function AuditList({ audit }) {
	if (!audit.length) {
		return <p className="muted">No audit entries are available.</p>;
	}

	return (
		<div className="field-list">
			{audit.map((entry, index) => (
				<div key={`${entry.stage}-${entry.timestamp}-${index}`} className="field-row">
					<p>
						<strong>{entry.stage}</strong> {entry.level || "INFO"}
					</p>
					<p>{entry.message}</p>
					<p className="muted">{entry.timestamp}</p>
				</div>
			))}
		</div>
	);
}

export default function VerifyPage({ auth, onLogout }) {
	const { sessionId } = useParams();
	const navigate = useNavigate();
	const [activeTab, setActiveTab] = useState("document");
	const [closeError, setCloseError] = useState("");
	const [isClosing, setIsClosing] = useState(false);
	const { documentUrl, error, isLoading, warnings, workspace } =
		useGeneralizedVerificationWorkspace({
			sessionId,
			token: auth.token,
		});

	const summaryStats = useMemo(() => {
		if (!workspace) {
			return [];
		}
		return [
			{ label: "Fields", value: workspace.summary.totalFields },
			{ label: "Green", value: workspace.summary.greenCount },
			{ label: "Amber", value: workspace.summary.amberCount },
			{ label: "Red", value: workspace.summary.redCount },
			{ label: "Risk", value: workspace.summary.riskLevel },
			{ label: "Match", value: formatPercent(workspace.summary.matchingScore) },
		];
	}, [workspace]);

	async function handleCloseSession() {
		setCloseError("");
		setIsClosing(true);

		try {
			await apiRequest(`/sessions/${sessionId}/close`, {
				method: "POST",
				token: auth.token,
			});
			startTransition(() => navigate("/upload"));
		} catch (requestError) {
			setCloseError(requestError.message);
		} finally {
			setIsClosing(false);
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
			{error ? <p className="error-text">{error}</p> : null}
			{closeError ? <p className="error-text">{closeError}</p> : null}

			{workspace ? (
				<div className="gv-workspace-layout">
					<aside className="gv-sidebar">
						<div className="panel">
							<p className="eyebrow">Verdict</p>
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
						</div>

						<div className="panel">
							<p className="eyebrow">Document</p>
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
						</div>

						<div className="panel">
							<p className="eyebrow">Summary</p>
							<div className="gv-stat-grid">
								{summaryStats.map((stat) => (
									<div key={stat.label} className="gv-stat-card">
										<span className="gv-stat-value">{stat.value}</span>
										<span className="gv-stat-label">{stat.label}</span>
									</div>
								))}
							</div>
						</div>
					</aside>

					<main className="gv-main-column">
						<div className="panel">
							<p className="eyebrow">Final verdict</p>
							<h2>{workspace.finalVerdict.explanation || "Workspace graph completed."}</h2>
							{workspace.finalVerdict.reasonCodes.length ? (
								<p className="muted">
									{workspace.finalVerdict.reasonCodes.join(", ")}
								</p>
							) : null}
						</div>

						<WorkspaceTabNav activeTab={activeTab} onChange={setActiveTab} />

						{activeTab === "document" ? (
							<DocumentTab
								documentUrl={documentUrl}
								documentMessage={
									documentUrl ? null : "No PDF is currently stored for this session."
								}
							/>
						) : null}

						{activeTab === "analysis" ? (
							<div className="gv-tab-panel">
								<div className="gv-panel-head">
									<div>
										<p className="eyebrow">Fields</p>
										<h2>Graph field decisions</h2>
									</div>
								</div>
								<div className="panel">
									<FieldList fields={workspace.fields} />
								</div>
								<div className="panel">
									<p className="eyebrow">Verifiers</p>
									<VerifierList verifiers={workspace.verifiers} />
								</div>
							</div>
						) : null}

						{activeTab === "audit" ? (
							<div className="gv-tab-panel">
								<div className="gv-panel-head">
									<div>
										<p className="eyebrow">Audit</p>
										<h2>Graph execution trail</h2>
									</div>
								</div>
								<div className="panel">
									<AuditList audit={workspace.audit} />
								</div>
							</div>
						) : null}
					</main>

					<aside className="gv-sidebar">
						<div className="panel">
							<p className="eyebrow">Actions</p>
							<div className="action-row">
								<button
									type="button"
									className="primary-btn"
									onClick={handleCloseSession}
									disabled={isClosing}
								>
									{isClosing ? "Closing..." : "Close Session"}
								</button>
							</div>
							{workspace.actions.length ? (
								<p className="muted">
									{workspace.actions
										.filter((action) => action.enabled !== false)
										.map((action) => action.label)
										.join(", ")}
								</p>
							) : null}
						</div>

						{warnings.length ? (
							<div className="panel">
								<p className="eyebrow">Notices</p>
								<div className="gv-warning-list">
									{warnings.map((warning) => (
										<p key={warning} className="muted">
											{warning}
										</p>
									))}
								</div>
							</div>
						) : null}
					</aside>
				</div>
			) : null}
		</div>
	);
}
