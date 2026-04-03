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

function ProviderStatusCard({ label, enabled, detail }) {
  return (
    <div className={`gv-provider-card ${enabled ? "is-enabled" : "is-disabled"}`}>
      <div className="gv-provider-card-head">
        <strong>{label}</strong>
        <span className={`gv-provider-dot ${enabled ? "is-on" : "is-off"}`} />
      </div>
      <p>{detail}</p>
    </div>
  );
}

export default function WorkspaceRightSidebar({
  session,
  analysisStatusLabel,
  analysisStatus,
  agentStatusLabel,
  agentUnderstandingSummary,
  executionStatusLabel,
  executionStatus,
  providerExecutionStatusLabel,
  providerExecutionStatus,
  providerExecutionSummary,
  providerOperatingMode,
  demoProfile,
  taskExecutionSummary,
  routingSummary,
  verificationSummary,
  overallOutcome,
  warnings,
}) {
  return (
    <aside className="gv-sidebar">
      <div className="panel">
        <p className="eyebrow">Readiness layers</p>
        <div className="gv-readiness-grid">
          <div className="gv-readiness-card">
            <span className="gv-detail-key">Workflow</span>
            <div><StatusBadge status={session.status} /></div>
          </div>
          <div className="gv-readiness-card">
            <span className="gv-detail-key">Analysis</span>
            <p>{analysisStatusLabel}</p>
          </div>
          <div className="gv-readiness-card">
            <span className="gv-detail-key">Execution</span>
            <p>{executionStatusLabel}</p>
          </div>
          <div className="gv-readiness-card">
            <span className="gv-detail-key">Agent</span>
            <p>{agentStatusLabel}</p>
          </div>
        </div>

        {session.worker_phase ? (
          <p className="muted" style={{ marginTop: "12px" }}>
            Worker phase: {session.worker_phase}
          </p>
        ) : null}

        {analysisStatus.generalized_analysis_error ? (
          <p className="error-text">{analysisStatus.generalized_analysis_error}</p>
        ) : null}
      </div>

      <div className="panel">
        <p className="eyebrow">External verifiers status</p>
        <div className="gv-provider-status-list">
          <ProviderStatusCard
            label={providerExecutionSummary.primaryTrustRailLabel}
            enabled={providerExecutionSummary.primaryTrustRailEnabled}
            detail={
              providerExecutionSummary.primaryTrustRailEnabled
                ? "Configured as the preferred VC trust rail."
                : "Preferred rail but not enabled in this environment."
            }
          />
          <ProviderStatusCard
            label="Supplementary providers"
            enabled={providerExecutionSummary.enabledExternalProviders.length > 0}
            detail={
              providerExecutionSummary.enabledExternalProviders.length
                ? providerExecutionSummary.enabledExternalProviders.join(", ")
                : "No supplementary external providers enabled."
            }
          />
          <ProviderStatusCard
            label="Provider execution"
            enabled={providerExecutionStatus.provider_execution_status === "READY"}
            detail={providerExecutionStatusLabel}
          />
        </div>
      </div>

      {/*<div className="panel">
        <p className="eyebrow">Agent-assisted understanding</p>
        <div className="gv-meta-stack">
          <span>
            <strong>Status:</strong> {agentStatusLabel}
          </span>
          <span>
            <strong>Type guess:</strong> {agentUnderstandingSummary.documentTypeGuess}
          </span>
          <span>
            <strong>Family guess:</strong> {agentUnderstandingSummary.documentFamilyGuess}
          </span>
          <span>
            <strong>Provider:</strong> {agentUnderstandingSummary.providerUsed || "deterministic"}
          </span>
        </div>
        <p className="muted">{agentUnderstandingSummary.reasoningSummary}</p>
        {agentUnderstandingSummary.manualReviewRecommended ? (
          <p className="muted">Agent-assisted review: manual review recommended.</p>
        ) : null}
        {agentUnderstandingSummary.warnings.length ? (
          <div className="gv-warning-list">
            {agentUnderstandingSummary.warnings.map((warning) => (
              <p key={warning} className="muted">
                {warning}
              </p>
            ))}
          </div>
        ) : null}
      </div>
      */}

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
        <p className="eyebrow">Provider execution</p>
        <div className="gv-meta-stack">
          <span>
            <strong>Status:</strong> {providerExecutionStatusLabel}
          </span>
          <span>
            <strong>Mode:</strong> {providerExecutionSummary.operatingModeLabel}
          </span>
          <span>
            <strong>Environment:</strong>{" "}
            {providerOperatingMode.execution_environment_label || "Not available"}
          </span>
          <span>
            <strong>Primary trust rail:</strong> {providerExecutionSummary.primaryTrustRailLabel}
          </span>
          <span>
            <strong>Entra enabled:</strong>{" "}
            {providerExecutionSummary.primaryTrustRailEnabled ? "Yes" : "No"}
          </span>
          <span>
            <strong>Traces:</strong> {providerExecutionSummary.traceCount}
          </span>
          <span>
            <strong>Outbound attempted:</strong>{" "}
            {providerExecutionSummary.outboundAttempted ? "Yes" : "No"}
          </span>
          <span>
            <strong>Fallback used:</strong>{" "}
            {providerExecutionSummary.fallbackUsed ? "Yes" : "No"}
          </span>
        </div>

        {demoProfile.seeded ? (
          <p className="muted">
            Demo profile: <strong>{demoProfile.profile_label}</strong>
          </p>
        ) : null}

        {providerExecutionStatus.provider_execution_error ? (
          <p className="error-text">{providerExecutionStatus.provider_execution_error}</p>
        ) : null}

        {providerExecutionSummary.providerKeysUsed.length ? (
          <div className="gv-chip-row">
            {providerExecutionSummary.providerKeysUsed.map((providerKey) => (
              <span key={providerKey} className="gv-chip">
                {providerKey}
              </span>
            ))}
          </div>
        ) : null}

        {providerExecutionSummary.enabledExternalProviders.length ? (
          <p className="muted">
            Enabled external providers:{" "}
            {providerExecutionSummary.enabledExternalProviders.join(", ")}
          </p>
        ) : (
          <p className="muted">
            No external providers are enabled. The bounded local mock path remains available.
          </p>
        )}

        {demoProfile.seeded ? <p className="muted">{demoProfile.description}</p> : null}

        {providerOperatingMode.provider_transition_notes.length ? (
          <div className="gv-warning-list">
            {providerOperatingMode.provider_transition_notes.map((note) => (
              <p key={note} className="muted">
                {note}
              </p>
            ))}
          </div>
        ) : null}

        {!providerExecutionSummary.primaryTrustRailEnabled ? (
          <p className="muted">
            Microsoft Entra Verified ID is the primary VC trust rail for Entra-aligned credentials,
            but it is not enabled in this environment.
          </p>
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

      {/*<div className="panel">
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
        <p className="muted">
          Mutation flows are intentionally deferred while the generalized workspace stays read-only.
        </p>
      </div>
      */}

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