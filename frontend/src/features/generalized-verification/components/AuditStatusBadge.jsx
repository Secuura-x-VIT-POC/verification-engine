import React from "react";
import { buildAuditStatusBadgeModel } from "../utils/viewModels";

export default function AuditStatusBadge({ status, outcomeColor }) {
  const badge = buildAuditStatusBadgeModel(status, outcomeColor);

  return <span className={`gv-status-badge gv-status-${badge.tone}`}>{badge.label}</span>;
}
