import React from "react";
import AuditDetailCard from "./AuditDetailCard";

export default function AuditTab({ auditDetails, emptyMessage }) {
  return (
    <div className="gv-tab-panel">
      <div className="gv-panel-head">
        <div>
          <p className="eyebrow">Audit view</p>
          <h2>Per-credential audit evidence</h2>
        </div>
      </div>

      {!auditDetails.length ? (
        <div className="panel">
          <p className="muted">{emptyMessage}</p>
        </div>
      ) : (
        <div className="gv-audit-list">
          {auditDetails.map((detail) => (
            <AuditDetailCard key={detail.credentialId} detail={detail} />
          ))}
        </div>
      )}
    </div>
  );
}
