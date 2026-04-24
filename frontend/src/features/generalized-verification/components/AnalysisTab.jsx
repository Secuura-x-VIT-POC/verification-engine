import React from "react";

export default function AnalysisTab({ rows, emptyMessage }) {
	return (
		<div className="gv-tab-panel">
			<div className="gv-panel-head">
				<div>
					<p className="eyebrow">Analysis view</p>
					<h2>Session-based verification</h2>
				</div>
			</div>

			<div className="panel">
				<p className="muted">
					Analysis data has been deprecated. The system now uses session-centric
					verification with real-time polling.
				</p>
				<p className="muted">
					Check the session status in the sidebar for current verification
					progress.
				</p>
			</div>
		</div>
	);
}
