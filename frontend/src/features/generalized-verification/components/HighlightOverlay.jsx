import React from "react";
import AuditStatusBadge from "./AuditStatusBadge";

export default function HighlightOverlay({ highlightItems, activeCredentialId, onSelectCredential }) {
  if (!highlightItems.length) {
    return null;
  }

  return (
    <div className="gv-highlight-layer">
      {highlightItems.map((item) => (
        <button
          key={item.credentialId}
          type="button"
          className={`gv-highlight gv-highlight-${item.outcomeColor} ${
            activeCredentialId === item.credentialId ? "is-active" : ""
          }`}
          style={{
            left: `${item.relativeBox.left}%`,
            top: `${item.relativeBox.top}%`,
            width: `${item.relativeBox.width}%`,
            height: `${item.relativeBox.height}%`,
          }}
          onClick={() => onSelectCredential(item.credentialId)}
          onMouseEnter={() => onSelectCredential(item.credentialId)}
          onFocus={() => onSelectCredential(item.credentialId)}
          title={`${item.label}: ${item.explanation}`}
        >
          <span className="sr-only">
            {item.label} - {item.documentValue}
          </span>
          <span className="gv-highlight-chip">
            <AuditStatusBadge status={item.auditStatus} outcomeColor={item.outcomeColor} />
          </span>
        </button>
      ))}
    </div>
  );
}
