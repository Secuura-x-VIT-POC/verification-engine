import React from "react";

export default function AuditReceiptPanel({ audit }) {
  if (!audit) return null;

  return (
    <div className="panel">
      <h2>Audit Receipt</h2>
      <p>
        <strong>Audit Event ID:</strong> {audit.audit_event_id}
      </p>
      <p>
        <strong>Logger Name:</strong> {audit.logger_name || "Not available"}
      </p>
      <p>
        <strong>Outcome:</strong> {audit.outcome}
      </p>
      <p>
        <strong>Reason Codes:</strong> {(audit.reason_codes || []).join(", ") || "None"}
      </p>
      <p>
        <strong>Issued At:</strong> {audit.issued_at}
      </p>
      <p>
        <strong>Document Commitment:</strong>{" "}
        {audit.document_commitment ? `${audit.document_commitment.slice(0, 18)}...` : "Unavailable"}
      </p>
    </div>
  );
}
