import React from "react";
export default function StatusBadge({ status }) {
  let className = "workflow-badge workflow-badge-neutral";

  if (status === "CREATED") className = "workflow-badge workflow-badge-created";
  else if (status === "UPLOADED") className = "workflow-badge workflow-badge-uploaded";
  else if (status === "PROCESSING") className = "workflow-badge workflow-badge-processing";
  else if (status === "VERIFIED") className = "workflow-badge workflow-badge-verified";
  else if (status === "PURGED") className = "workflow-badge workflow-badge-purged";
  else if (status === "FAILED") className = "workflow-badge workflow-badge-failed";

  return <span className={className}>{status}</span>;
}