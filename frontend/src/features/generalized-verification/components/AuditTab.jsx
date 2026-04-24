import React from "react";

export default function AuditTab({ auditDetails, emptyMessage }) {
	return (
		<div className="gv-tab-panel">
			<div className="gv-panel-head">
				<div>
					<p className="eyebrow">Audit view</p>
					<h2>Session verification results</h2>
				</div>
			</div>

			<div className="panel">
				<p className="muted">
					Detailed audit data has been deprecated. The system now provides
					session-level verification results.
				</p>
				<p className="muted">
					Check the session result in the sidebar for final verification
					outcome.
				</p>
			</div>
		</div>
	);
}
