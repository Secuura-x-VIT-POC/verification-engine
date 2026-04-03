import React from "react";
import StatusBadge from "../../../components/StatusBadge";

function OutcomeBadge({ outcome }) {
  if (outcome === "GREEN") {
    return <span className="badge badge-green">GREEN</span>;
  }
  if (outcome === "AMBER") {
    return <span className="badge badge-amber">AMBER</span>;
  }
  if (outcome === "RED") {
    return <span className="badge badge-red">RED</span>;
  }
  return <span className="gv-status-badge gv-status-neutral">Pending</span>;
}

export default function WorkspaceRightSidebar({
  session,
  analysisStatusLabel,
  analysisStatus,
  executionStatusLabel,
  executionStatus,
  taskExecutionSummary,
  routingSummary,
  verificationSummary,
  overallOutcome,
  warnings,
}) {
  return (
    <aside className="gv-sidebar">
      <div className="panel">
        <p className="eyebrow">Readiness</p>
        <div className="gv-meta-stack">
          <span>
            <strong>Workflow:</strong> <StatusBadge status={session.status} />
          </span>
          <span>
            <strong>Analysis:</strong> {analysisStatusLabel}
          </span>
          {session.worker_phase ? (
            <span>
              <strong>Worker phase:</strong> {session.worker_phase}
            </span>
          ) : null}
        </div>

        {analysisStatus.generalized_analysis_error ? (
          <p className="error-text">{analysisStatus.generalized_analysis_error}</p>
        ) : null}
      </div>

      <div className="panel">
        <p className="eyebrow">Task execution</p>
        <div className="gv-meta-stack">
          <span>
            <strong>Status:</strong> {executionStatusLabel}
          </span>
          <span>
            <strong>Total tasks:</strong> {taskExecutionSummary.totalTasks}
          </span>
          <span>
            <strong>Succeeded:</strong> {taskExecutionSummary.counts.SUCCEEDED}
          </span>
          <span>
            <strong>Partial:</strong> {taskExecutionSummary.counts.PARTIAL}
          </span>
          <span>
            <strong>Manual review:</strong> {taskExecutionSummary.counts.MANUAL_REVIEW}
          </span>
        </div>

        {executionStatus.verification_execution_error ? (
          <p className="error-text">{executionStatus.verification_execution_error}</p>
        ) : null}

        {taskExecutionSummary.verifierKeysUsed.length ? (
          <div className="gv-chip-row">
            {taskExecutionSummary.verifierKeysUsed.map((verifierKey) => (
              <span key={verifierKey} className="gv-chip">
                {verifierKey}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="panel">
        <p className="eyebrow">Verifier routing</p>
        {routingSummary.length ? (
          <div className="gv-count-list">
            {routingSummary.map((entry) => (
              <div key={entry.label} className="gv-count-row">
                <span>{entry.label}</span>
                <strong>{entry.count}</strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">No routing summary is available yet.</p>
        )}
      </div>

      <div className="panel">
        <p className="eyebrow">Overall outcome</p>
        <OutcomeBadge outcome={overallOutcome} />
        <div className="gv-meta-stack" style={{ marginTop: "12px" }}>
          <span>
            <strong>Manual review count:</strong> {verificationSummary.manual_review_count}
          </span>
          <span>
            <strong>Verified fields:</strong> {verificationSummary.total_credentials_verified}
          </span>
        </div>

        {verificationSummary.overall_reason_codes.length ? (
          <div className="gv-chip-row">
            {verificationSummary.overall_reason_codes.map((reasonCode) => (
              <span key={reasonCode} className="gv-chip">
                {reasonCode}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="panel">
        <p className="eyebrow">Reviewer actions</p>
        <div className="action-row">
          <button type="button" className="secondary-btn" disabled>
            Approve
          </button>
          <button type="button" className="secondary-btn" disabled>
            Override
          </button>
          <button type="button" className="secondary-btn" disabled>
            Add Note
          </button>
        </div>
        <p className="muted">Mutation flows are intentionally deferred while the generalized workspace stays read-only.</p>
      </div>

      {warnings.length ? (
        <div className="panel">
          <p className="eyebrow">Partial data notices</p>
          <div className="gv-warning-list">
            {warnings.map((warning) => (
              <p key={warning} className="muted">
                {warning}
              </p>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}
