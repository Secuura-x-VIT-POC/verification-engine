import React from "react";
import AuditStatusBadge from "./AuditStatusBadge";

export default function AnalysisTab({ rows, emptyMessage }) {
  return (
    <div className="gv-tab-panel">
      <div className="gv-panel-head">
        <div>
          <p className="eyebrow">Analysis view</p>
          <h2>Credentials, routing, and verification need</h2>
        </div>
      </div>

      {!rows.length ? (
        <div className="panel">
          <p className="muted">{emptyMessage}</p>
        </div>
      ) : (
        <div className="gv-analysis-list">
          {rows.map((row) => (
            <article key={row.credentialId} className="panel gv-analysis-row">
              <div className="gv-analysis-title">
                <div>
                  <h3>{row.label}</h3>
                  <p className="muted">{row.category}</p>
                </div>
                <AuditStatusBadge status={row.auditStatus} outcomeColor={row.outcomeColor} />
              </div>

              <div className="gv-analysis-grid">
                <div>
                  <span className="gv-detail-key">Extracted value</span>
                  <p>{row.extractedValue}</p>
                </div>
                <div>
                  <span className="gv-detail-key">Normalized value</span>
                  <p>{row.normalizedValue || "Unavailable"}</p>
                </div>
                <div>
                  <span className="gv-detail-key">Requires verification</span>
                  <p>{row.requiresVerification ? "Yes" : "No"}</p>
                </div>
                <div>
                  <span className="gv-detail-key">Selected verifier</span>
                  <p>{row.verifierLabel}</p>
                </div>
                <div>
                  <span className="gv-detail-key">Task outcome</span>
                  <p>{row.taskStatus || "Pending"}</p>
                </div>
              </div>

              {row.verificationReason || row.routeReason || row.reasonCodes.length ? (
                <div className="gv-analysis-notes">
                  {row.verificationReason ? <p><strong>Why verify:</strong> {row.verificationReason}</p> : null}
                  {row.routeReason ? <p><strong>Route reason:</strong> {row.routeReason}</p> : null}
                  {row.reasonCodes.length ? <p><strong>Reason codes:</strong> {row.reasonCodes.join(", ")}</p> : null}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
