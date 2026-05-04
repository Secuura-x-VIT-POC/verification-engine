import React from "react";
import { buildHighlightStyle } from "../utils/highlightGeometry.js";

export default function HighlightOverlay({
	highlightItems,
	activeCredentialId,
	onSelectCredential,
	pageSize,
}) {
	if (!highlightItems.length) {
		return null;
	}

	return (
		<div className="gv-highlight-layer">
			{highlightItems.map((item) => (
				<button
					key={item.id || item.credentialId}
					type="button"
					className={`gv-highlight gv-highlight-${item.outcomeColor} ${
						activeCredentialId === item.credentialId ? "is-active" : ""
					}`}
					style={{
						...buildHighlightStyle(item, pageSize),
					}}
					onClick={() => onSelectCredential(item.credentialId)}
					onMouseEnter={() => onSelectCredential(item.credentialId)}
					onFocus={() => onSelectCredential(item.credentialId)}
					title={`${item.label}: ${item.explanation}`}
				>
					<span className="sr-only">
						{item.label} - {item.documentValue}
					</span>
				</button>
			))}
		</div>
	);
}

