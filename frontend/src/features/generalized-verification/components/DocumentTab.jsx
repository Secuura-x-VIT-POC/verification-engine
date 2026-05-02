import React, { useMemo } from "react";
import DocumentHighlightViewer from "./DocumentHighlightViewer";

function asArray(value) {
	return Array.isArray(value) ? value : [];
}

function getStatusCounts(highlightItems) {
	return highlightItems.reduce(
		(counts, item) => {
			const status = String(item.auditStatus || item.status || "")
				.trim()
				.toUpperCase();

			if (status === "GREEN") counts.green += 1;
			else if (status === "RED") counts.red += 1;
			else counts.amber += 1;

			return counts;
		},
		{ green: 0, amber: 0, red: 0 }
	);
}

function getSelectedHighlight(highlightItems, selectedCredentialId) {
	if (!selectedCredentialId) return null;

	return highlightItems.find(
		(item) =>
			item.credentialId === selectedCredentialId ||
			item.fieldId === selectedCredentialId ||
			item.id === selectedCredentialId
	);
}

export default function DocumentTab({
	documentUrl,
	highlightItems = [],
	selectedAuditDetail,
	onSelectCredential,
	selectedCredentialId,
	documentMessage,
}) {
	const safeHighlightItems = asArray(highlightItems);

	const statusCounts = useMemo(
		() => getStatusCounts(safeHighlightItems),
		[safeHighlightItems]
	);

	const selectedHighlight = useMemo(
		() => getSelectedHighlight(safeHighlightItems, selectedCredentialId),
		[safeHighlightItems, selectedCredentialId]
	);

	return (
		<div className="gv-tab-panel">
			<div className="gv-panel-head">
				<div>
					<p className="eyebrow">Document review</p>
					<h2>Session document</h2>
					<p className="muted">
						Hover or click a PDF highlight to inspect the matching field.
					</p>
				</div>

				{documentMessage ? <p className="muted">{documentMessage}</p> : null}
			</div>

			<div className="gv-document-layout">
				<div className="gv-card">
					<DocumentHighlightViewer
						documentUrl={documentUrl}
						highlightItems={safeHighlightItems}
						activeCredentialId={selectedCredentialId}
						onSelectCredential={onSelectCredential}
					/>
				</div>

				<aside className="gv-card">
					<p className="eyebrow">PDF Highlights</p>

					<div className="gv-stat-grid">
						<div className="gv-stat-card">
							<span className="gv-stat-value">{safeHighlightItems.length}</span>
							<span className="gv-stat-label">Total</span>
						</div>

						<div className="gv-stat-card">
							<span className="gv-stat-value">{statusCounts.green}</span>
							<span className="gv-stat-label">Green</span>
						</div>

						<div className="gv-stat-card">
							<span className="gv-stat-value">{statusCounts.amber}</span>
							<span className="gv-stat-label">Amber</span>
						</div>

						<div className="gv-stat-card">
							<span className="gv-stat-value">{statusCounts.red}</span>
							<span className="gv-stat-label">Red</span>
						</div>
					</div>

					{selectedHighlight ? (
						<div className="field-row" style={{ marginTop: "16px" }}>
							<p>
								<strong>{selectedHighlight.label || "Selected field"}</strong>
							</p>
							<p className="muted">
								Value: {selectedHighlight.documentValue || "Hidden"}
							</p>
							<p className="muted">
								Status: {selectedHighlight.auditStatus || "AMBER"}
							</p>
							<p className="muted">Page: {selectedHighlight.page || 1}</p>
							<p className="muted">
								{selectedHighlight.explanation ||
									"No explanation available for this highlight."}
							</p>
						</div>
					) : (
						<p className="muted" style={{ marginTop: "16px" }}>
							Select a highlight to see details here.
						</p>
					)}

					{selectedAuditDetail ? (
						<div className="field-row" style={{ marginTop: "16px" }}>
							<p>
								<strong>Selected audit detail</strong>
							</p>
							<p className="muted">
								{selectedAuditDetail.summary ||
									selectedAuditDetail.message ||
									"Audit detail selected."}
							</p>
						</div>
					) : null}
				</aside>
			</div>
		</div>
	);
}