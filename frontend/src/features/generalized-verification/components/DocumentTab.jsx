import React from "react";
import AuditDetailCard from "./AuditDetailCard";
import DocumentHighlightViewer from "./DocumentHighlightViewer";

export default function DocumentTab({
  documentUrl,
  highlightItems,
  selectedAuditDetail,
  onSelectCredential,
  selectedCredentialId,
  documentMessage,
}) {
  return (
    <div className="gv-tab-panel">
      <div className="gv-panel-head">
        <div>
          <p className="eyebrow">Document review</p>
          <h2>PDF with verification overlays</h2>
        </div>
        {documentMessage ? <p className="muted">{documentMessage}</p> : null}
      </div>

      <div className="gv-document-layout">
        <div className="panel">
          <DocumentHighlightViewer
            documentUrl={documentUrl}
            highlightItems={highlightItems}
            activeCredentialId={selectedCredentialId}
            onSelectCredential={onSelectCredential}
          />
        </div>

        <AuditDetailCard detail={selectedAuditDetail} compact />
      </div>
    </div>
  );
}
