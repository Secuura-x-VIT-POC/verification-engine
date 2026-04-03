import React from "react";
import AuditStatusBadge from "./AuditStatusBadge";

function renderFieldPairs(fields) {
  const entries = Object.entries(fields || {});
  if (!entries.length) {
    return null;
  }

  return (
    <div className="gv-detail-grid">
      {entries.map(([key, value]) => (
        <div key={key} className="gv-detail-pill">
          <span className="gv-detail-key">{key}</span>
          <span>{typeof value === "object" && value !== null
            ? JSON.stringify(value, null, 2)
            : String(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function AuditDetailCard({ detail, compact = false }) {
  if (!detail) {
    return (
      <div className="panel">
        <p className="muted">Select a credential highlight or list item to inspect its audit detail.</p>
      </div>
    );
  }

  return (
    <article className={`panel gv-audit-card ${compact ? "is-compact" : ""}`}>
      <div className="gv-card-header">
        <div>
          <p className="eyebrow">Credential audit</p>
          <h2>{detail.label}</h2>
        </div>
        <AuditStatusBadge status={detail.auditStatus} outcomeColor={detail.outcomeColor} />
      </div>

      <div className="gv-inline-meta">
        <span>
          <strong>Verifier:</strong> {detail.verifierLabel}
        </span>
        {detail.execution ? (
          <span>
            <strong>Task:</strong> {detail.execution.label}
          </span>
        ) : null}
        {detail.execution?.providerLabel ? (
          <span>
            <strong>Executed provider:</strong> {detail.execution.providerLabel}
          </span>
        ) : null}
        {detail.preferredProviderLabel ? (
          <span>
            <strong>Preferred provider:</strong> {detail.preferredProviderLabel}
          </span>
        ) : null}
      </div>

      <div className="gv-compact-summary-grid">
        <div className="gv-compact-summary-card">
          <span className="gv-detail-key">Value</span>
          <p>{detail.documentValue}</p>
        </div>

        {detail.normalizedValue ? (
          <div className="gv-compact-summary-card">
            <span className="gv-detail-key">Normalized</span>
            <p>{detail.normalizedValue}</p>
          </div>
        ) : null}

        <div className="gv-compact-summary-card">
          <span className="gv-detail-key">Category</span>
          <p>{detail.category}</p>
        </div>

        {detail.timestamp ? (
          <div className="gv-compact-summary-card">
            <span className="gv-detail-key">Updated</span>
            <p>{detail.timestamp}</p>
          </div>
        ) : null}
      </div>

      <p className="gv-card-copy">{detail.explanation}</p>

      {detail.reasonCodes.length ? (
        <div className="gv-chip-row">
          {detail.reasonCodes.map((reasonCode) => (
            <span key={reasonCode} className="gv-chip">
              {reasonCode}
            </span>
          ))}
        </div>
      ) : null}

      {detail.agentAssisted ? (
        <div className="gv-chip-row">
          <span className="gv-chip">Agent-assisted</span>
        </div>
      ) : null}

      {compact ? (
        <>
          {detail.routeDispositionMessage ? (
            <p className="muted">{detail.routeDispositionMessage}</p>
          ) : null}

          {renderFieldPairs(detail.mismatchedFields) ? (
            <section className="gv-card-section">
              <h3>Mismatched fields</h3>
              {renderFieldPairs(detail.mismatchedFields)}
            </section>
          ) : null}

          {detail.missingFields.length ? (
            <section className="gv-card-section">
              <h3>Missing fields</h3>
              <div className="gv-chip-row">
                {detail.missingFields.map((field) => (
                  <span key={field} className="gv-chip gv-chip-muted">
                    {field}
                  </span>
                ))}
              </div>
            </section>
          ) : null}
        </>
      ) : (
        <>
          {detail.agentInfo || detail.agentExplanation ? (
            <section className="gv-card-section">
              <h3>Agent-assisted context</h3>
              {detail.agentInfo ? (
                <div className="gv-inline-meta">
                  <span>
                    <strong>Candidate:</strong> {detail.agentInfo.candidateLabel}
                  </span>
                  {detail.agentInfo.recommendedVerifierLabel ? (
                    <span>
                      <strong>Recommended verifier:</strong> {detail.agentInfo.recommendedVerifierLabel}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {detail.agentInfo?.routeReason ? <p>{detail.agentInfo.routeReason}</p> : null}
              {detail.agentExplanation ? <p>{detail.agentExplanation}</p> : null}
            </section>
          ) : null}

          {detail.execution ? (
            <section className="gv-card-section">
              <h3>Task execution</h3>
              <div className="gv-inline-meta">
                <span>
                  <strong>Status:</strong> {detail.execution.label}
                </span>
                <span>
                  <strong>Attempts:</strong> {detail.execution.resultCount}
                </span>
                {detail.routeDispositionLabel ? (
                  <span>
                    <strong>Route:</strong> {detail.routeDispositionLabel}
                  </span>
                ) : null}
                {detail.execution.providerTechnicalStatus ? (
                  <span>
                    <strong>Provider status:</strong> {detail.execution.providerTechnicalStatus}
                  </span>
                ) : null}
                {detail.execution.providerExecutionEnvironmentLabel ? (
                  <span>
                    <strong>Environment:</strong> {detail.execution.providerExecutionEnvironmentLabel}
                  </span>
                ) : null}
                {detail.execution.confidence !== null ? (
                  <span>
                    <strong>Confidence:</strong> {detail.execution.confidence}
                  </span>
                ) : null}
              </div>
              {detail.routeDispositionMessage ? <p className="muted">{detail.routeDispositionMessage}</p> : null}
              {detail.execution.providerDemoProfileKey ? (
                <p className="muted">Seeded demo profile: {detail.execution.providerDemoProfileKey}</p>
              ) : null}
              {detail.execution.providerIsDemoResult ? (
                <p className="muted">
                  This provider result is a deterministic demo-mock response, not a live external call.
                </p>
              ) : null}
              {detail.execution.providerIsLiveResult ? (
                <p className="muted">This provider result came from a live-configured provider path.</p>
              ) : null}
              {detail.execution.providerFallbackUsed ? (
                <p className="muted">
                  Provider-backed execution fell back to the bounded local verifier path.
                </p>
              ) : null}
              {detail.execution.providerTransitionNotes?.length ? (
                <div className="gv-warning-list">
                  {detail.execution.providerTransitionNotes.map((note) => (
                    <p key={note} className="muted">
                      {note}
                    </p>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}

          {renderFieldPairs(detail.matchedFields) ? (
            <section className="gv-card-section">
              <h3>Matched fields</h3>
              {renderFieldPairs(detail.matchedFields)}
            </section>
          ) : null}

          {renderFieldPairs(detail.mismatchedFields) ? (
            <section className="gv-card-section">
              <h3>Mismatched fields</h3>
              {renderFieldPairs(detail.mismatchedFields)}
            </section>
          ) : null}

          {detail.missingFields.length ? (
            <section className="gv-card-section">
              <h3>Missing fields</h3>
              <div className="gv-chip-row">
                {detail.missingFields.map((field) => (
                  <span key={field} className="gv-chip gv-chip-muted">
                    {field}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          {detail.evidence.length ? (
            <section className="gv-card-section">
              <h3>Evidence</h3>
              <div className="gv-evidence-list">
                {detail.evidence.map((item, index) => (
                  <div key={`${item.source}-${index}`} className="gv-evidence-card">
                    <p>
                      <strong>{item.source}</strong> · {item.evidence_type}
                    </p>
                    <pre>{JSON.stringify(item.detail, null, 2)}</pre>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}

      {!compact ? (
        <div className="gv-card-footer">
          {detail.isFallback ? <span className="muted">Derived from extracted data only</span> : null}
        </div>
      ) : null}
    </article>
  );
}