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

              <div className="gv-analysis-section">
                <div className="gv-analysis-section-title">Field details</div>
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
                    <span className="gv-detail-key">Task outcome</span>
                    <p>{row.taskStatus || "Pending"}</p>
                  </div>
                </div>
              </div>

              <div className="gv-analysis-section">
                <div className="gv-analysis-section-title">Route and provider</div>
                <div className="gv-analysis-grid">
                  <div>
                    <span className="gv-detail-key">Selected verifier</span>
                    <p>{row.verifierLabel}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">Route preference</span>
                    <p>{row.routeDispositionLabel || "Standard route"}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">Preferred provider</span>
                    <p>{row.preferredProviderLabel || "No provider preference"}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">Planned provider</span>
                    <p>{row.plannedProviderLabel || "No provider planned"}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">Executed provider</span>
                    <p>{row.providerLabel || "No provider used"}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">Provider mode</span>
                    <p>{row.providerOperatingModeLabel || "Not available"}</p>
                  </div>
                </div>
              </div>

              <div className="gv-analysis-section">
                <div className="gv-analysis-section-title">Agent-assisted and notes</div>
                <div className="gv-analysis-grid">
                  <div>
                    <span className="gv-detail-key">Agent-assisted route</span>
                    <p>{row.agentRecommendedVerifierLabel || "No agent recommendation"}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">Provider status</span>
                    <p>{row.providerTechnicalStatus || "Not available"}</p>
                  </div>
                </div>
              </div>

              {row.verificationReason ||
              row.routeReason ||
              row.agentRouteReason ||
              row.reasonCodes.length ? (
                <div className="gv-analysis-notes">
                  {row.verificationReason ? (
                    <p>
                      <strong>Why verify:</strong> {row.verificationReason}
                    </p>
                  ) : null}
                  {row.routeReason ? (
                    <p>
                      <strong>Route reason:</strong> {row.routeReason}
                    </p>
                  ) : null}
                  {row.routeDispositionMessage ? (
                    <p>
                      <strong>Provider path:</strong> {row.routeDispositionMessage}
                    </p>
                  ) : null}
                  {row.providerExecutionEnvironmentLabel ? (
                    <p>
                      <strong>Environment:</strong> {row.providerExecutionEnvironmentLabel}
                    </p>
                  ) : null}
                  {row.providerDemoProfileKey ? (
                    <p>
                      <strong>Demo profile:</strong> {row.providerDemoProfileKey}
                    </p>
                  ) : null}
                  {row.providerIsDemoResult ? (
                    <p>
                      <strong>Execution mode:</strong> Seeded demo-mock response.
                    </p>
                  ) : null}
                  {row.providerIsLiveResult ? (
                    <p>
                      <strong>Execution mode:</strong> Live-configured provider response.
                    </p>
                  ) : null}
                  {row.providerFallbackUsed ? (
                    <p>
                      <strong>Provider fallback:</strong> Local deterministic fallback was used.
                    </p>
                  ) : null}
                  {row.agentRouteReason ? (
                    <p>
                      <strong>Agent-assisted:</strong> {row.agentRouteReason}
                    </p>
                  ) : null}
                  {row.agentManualReviewRecommended ? (
                    <p>
                      <strong>Agent review flag:</strong> Manual review suggested.
                    </p>
                  ) : null}
                  {row.reasonCodes.length ? (
                    <p>
                      <strong>Reason codes:</strong> {row.reasonCodes.join(", ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}