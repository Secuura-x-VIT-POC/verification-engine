import React from "react";
import AuditStatusBadge from "./AuditStatusBadge";

const STATUS_OPTIONS = [
  "ALL",
  "VERIFIED",
  "MISMATCH",
  "PARTIAL",
  "UNVERIFIED",
  "MANUAL_REVIEW",
  "NOT_APPLICABLE",
];

export default function WorkspaceLeftSidebar({
  documentProfile,
  summaryStats,
  statusCounts,
  credentialItems,
  selectedCredentialId,
  onSelectCredential,
  filters,
  onChangeFilters,
  availableCategories,
}) {
  const activeStatusCounts = Object.entries(statusCounts).filter(([, count]) => count > 0);

  const flaggedCredentials = credentialItems.filter(
    (item) =>
      item.auditStatus === "MISMATCH" ||
      item.auditStatus === "PARTIAL" ||
      item.auditStatus === "MANUAL_REVIEW"
  );

  function updateFilter(key, value) {
    onChangeFilters((current) => ({
      ...current,
      [key]: value,
    }));
  }

  return (
    <aside className="gv-sidebar">
      <div className="panel">
        <p className="eyebrow">Document overview</p>
        <h2>{documentProfile.document_type}</h2>
        <div className="gv-meta-stack">
          <span>
            <strong>Family:</strong> {documentProfile.document_family}
          </span>
          <span>
            <strong>Pages:</strong> {documentProfile.page_count ?? "Unknown"}
          </span>
          <span>
            <strong>PII detected:</strong> {documentProfile.pii_detected ? "Yes" : "No"}
          </span>
          <span>
            <strong>Manual review:</strong>{" "}
            {documentProfile.requires_manual_review ? "Recommended" : "Not flagged"}
          </span>
        </div>

        {documentProfile.detected_categories.length ? (
          <div className="gv-chip-row">
            {documentProfile.detected_categories.map((category) => (
              <span key={category} className="gv-chip">
                {category}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="panel">
        <p className="eyebrow">Review filters</p>

        <div className="gv-filter-stack">
          <label className="gv-filter-field">
            <span className="gv-detail-key">Status</span>
            <select
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
            >
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>

          <label className="gv-filter-field">
            <span className="gv-detail-key">Category</span>
            <select
              value={filters.category}
              onChange={(event) => updateFilter("category", event.target.value)}
            >
              <option value="ALL">ALL</option>
              {availableCategories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>

          <label className="gv-checkbox-row">
            <input
              type="checkbox"
              checked={filters.piiOnly}
              onChange={(event) => updateFilter("piiOnly", event.target.checked)}
            />
            <span>PII only</span>
          </label>

          <label className="gv-checkbox-row">
            <input
              type="checkbox"
              checked={filters.manualReviewOnly}
              onChange={(event) =>
                updateFilter("manualReviewOnly", event.target.checked)
              }
            />
            <span>Manual review only</span>
          </label>
        </div>
      </div>

      <div className="panel">
        <p className="eyebrow">Summary counts</p>
        <div className="gv-stat-grid">
          {summaryStats.map((stat) => (
            <div key={stat.label} className="gv-stat-card">
              <span className="gv-stat-value">{stat.value}</span>
              <span className="gv-stat-label">{stat.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <p className="eyebrow">Field status mix</p>
        {activeStatusCounts.length ? (
          <div className="gv-count-list">
            {activeStatusCounts.map(([status, count]) => (
              <div key={status} className="gv-count-row">
                <AuditStatusBadge status={status} />
                <span>{count}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">No audit counts are available yet.</p>
        )}
      </div>

      <div className="panel">
        <p className="eyebrow">Extracted credentials</p>
        {credentialItems.length ? (
          <div className="gv-credential-list">
            {credentialItems.map((item) => (
              <button
                key={item.credentialId}
                type="button"
                className={`gv-credential-btn ${
                  selectedCredentialId === item.credentialId ? "is-active" : ""
                }`}
                onClick={() => onSelectCredential(item.credentialId)}
              >
                <div>
                  <strong>{item.label}</strong>
                  <p>{item.documentValue}</p>
                </div>
                <AuditStatusBadge status={item.auditStatus} outcomeColor={item.outcomeColor} />
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">No credentials are available for this session yet.</p>
        )}
      </div>
    </aside>
  );
}