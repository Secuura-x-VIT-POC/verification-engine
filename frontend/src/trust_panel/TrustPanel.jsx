import React from "react";
export default function TrustPanel({ trust }) {
  if (!trust) return null;

  let trustClass = "";

  if (trust.outcome === "GREEN") trustClass = "badge badge-green";
  else if (trust.outcome === "AMBER") trustClass = "badge badge-amber";
  else if (trust.outcome === "RED") trustClass = "badge badge-red";
  else return null;

  return (
    <div className="panel">
      <h2>Trust Result</h2>
      <p>
        <strong>Outcome:</strong> <span className={trustClass}>{trust.outcome}</span>
      </p>
      <p>
        <strong>Reason Codes:</strong> {(trust.reason_codes || []).join(", ") || "None"}
      </p>
      <p>
        <strong>Connector IDs:</strong> {(trust.connector_ids || []).join(", ") || "None"}
      </p>
    </div>
  );
}
