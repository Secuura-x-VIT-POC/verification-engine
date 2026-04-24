import React from "react";
import StatusBadge from "../../../components/StatusBadge";

function OutcomeBadge({ outcome }) {
	if (outcome === "GREEN") {
		return <span className="badge badge-green">GREEN</span>;
	}
	if (outcome === "AMBER") {
		return <span className="badge badge-amber">AMBER</span>;
	}
	if (outcome === "RED") {
		return <span className="badge badge-red">RED</span>;
	}
	return <span className="gv-status-badge gv-status-neutral">Pending</span>;
}

export default function WorkspaceRightSidebar({
	session,
	analysisStatusLabel,
	analysisStatus,
	agentStatusLabel,
	agentUnderstandingSummary,
	executionStatusLabel,
	executionStatus,
	providerExecutionStatusLabel,
	providerExecutionStatus,
	providerExecutionSummary,
	providerOperatingMode,
	demoProfile,
	taskExecutionSummary,
	routingSummary,
	verificationSummary,
	overallOutcome,
	warnings,
}) {
	const sessionStatus = session?.status || "UNKNOWN";
	const sessionResult = session?.result || {};

	return (
		<aside className="gv-sidebar">
			<div className="panel">
				<p className="eyebrow">Session Status</p>
				<div className="gv-meta-stack">
					<span>
						<strong>Status:</strong> <StatusBadge status={sessionStatus} />
					</span>
					<span>
						<strong>Worker Phase:</strong> {session?.worker_phase || "Waiting"}
					</span>
					<span>
						<strong>Updated:</strong> {session?.updated_at || "N/A"}
					</span>
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Processing</p>
				<div className="gv-meta-stack">
					<span>
						<strong>Status:</strong>{" "}
						{sessionStatus === "VERIFYING" ? "In Progress" : "Complete"}
					</span>
					{sessionStatus === "VERIFYING" && (
						<div className="spinner" style={{ margin: "8px 0" }}></div>
					)}
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Result</p>
				<div className="gv-meta-stack">
					<span>
						<strong>Outcome:</strong> {sessionResult?.outcome || "Pending"}
					</span>
					<span>
						<strong>Reason:</strong> {sessionResult?.reason || "N/A"}
					</span>
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Summary</p>
				<div className="gv-meta-stack">
					<span>
						<strong>Verification completed</strong>
					</span>
					<span>
						<strong>Connectors used:</strong>{" "}
						{session?.connectors_used?.length || 0}
					</span>
					<span>
						<strong>Timestamp:</strong> {session?.updated_at || "N/A"}
					</span>
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Session Actions</p>
				<div className="action-row">
					<button type="button" className="secondary-btn" disabled>
						View Receipt
					</button>
					<button type="button" className="secondary-btn" disabled>
						Export
					</button>
				</div>
				<p className="muted">Actions available after verification completes.</p>
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
	);
}
