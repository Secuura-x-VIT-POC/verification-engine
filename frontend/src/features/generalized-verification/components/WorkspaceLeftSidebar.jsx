import React from "react";
import AuditStatusBadge from "./AuditStatusBadge";

export default function WorkspaceLeftSidebar({
	documentProfile,
	summaryStats,
	statusCounts,
	credentialItems,
	selectedCredentialId,
	onSelectCredential,
}) {
	return (
		<aside className="gv-sidebar">
			<div className="panel">
				<p className="eyebrow">Session Overview</p>
				<h2>Verification Session</h2>
				<div className="gv-meta-stack">
					<span>
						<strong>Status:</strong>{" "}
						{summaryStats.find((s) => s.label === "Status")?.value || "Unknown"}
					</span>
					<span>
						<strong>Outcome:</strong>{" "}
						{summaryStats.find((s) => s.label === "Outcome")?.value ||
							"Pending"}
					</span>
					<span>
						<strong>Connectors:</strong>{" "}
						{summaryStats.find((s) => s.label === "Connectors")?.value || 0}
					</span>
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Session Stats</p>
				<div className="gv-stat-grid">
					{summaryStats.map((stat) => (
						<div key={stat.label} className="gv-stat-card">
							<span className="gv-stat-value">{stat.value}</span>
							<span className="gv-stat-label">{stat.label}</span>
						</div>
					))}
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Document</p>
				<div className="gv-meta-stack">
					<span>
						<strong>Available:</strong> {documentProfile ? "Yes" : "No"}
					</span>
					<span>
						<strong>Filename:</strong> {documentProfile?.filename || "N/A"}
					</span>
				</div>
			</div>

			<div className="panel">
				<p className="eyebrow">Actions</p>
				<div className="action-row">
					<button type="button" className="secondary-btn" disabled>
						View Details
					</button>
				</div>
				<p className="muted">Session actions available after completion.</p>
			</div>
		</aside>
	);
}
