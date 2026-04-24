import React from "react";

export default function DocumentTab({
	documentUrl,
	highlightItems,
	selectedAuditDetail,
	onSelectCredential,
	selectedCredentialId,
	documentMessage,
}) {
	return (
		<div className="gv-tab-panel">
			<div className="gv-panel-head">
				<div>
					<p className="eyebrow">Document review</p>
					<h2>Session document</h2>
				</div>
				{documentMessage ? <p className="muted">{documentMessage}</p> : null}
			</div>

			<div className="gv-document-layout">
				<div className="panel">
					{documentUrl ? (
						<iframe
							src={documentUrl}
							style={{ width: "100%", height: "600px", border: "none" }}
							title="Document Viewer"
						/>
					) : (
						<p className="muted">No document available for this session.</p>
					)}
				</div>
			</div>
		</div>
	);
}
