import React from "react";

const TABS = [
  { id: "document", label: "Document" },
  { id: "analysis", label: "Analysis" },
  { id: "audit", label: "Audit" },
];

export default function WorkspaceTabNav({ activeTab, onChange }) {
  return (
    <div className="gv-tab-nav" role="tablist" aria-label="Generalized verification views">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`gv-tab-btn ${activeTab === tab.id ? "is-active" : ""}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
