import React from "react";

const STATUS_CLASS_MAP = {
  CREATED: "workflow-badge-created",
  UPLOAD_PENDING: "workflow-badge-uploaded",
  UPLOADED_PENDING_REVIEW: "workflow-badge-uploaded",
  VERIFYING: "workflow-badge-processing",
  VERIFIED_GREEN: "workflow-badge-verified-green",
  VERIFIED_AMBER: "workflow-badge-verified-amber",
  VERIFIED_RED: "workflow-badge-failed",
  ABANDONED_VERIFYING: "workflow-badge-failed",
  FAILED_RETRIABLE: "workflow-badge-failed",
  FAILED_PURGED: "workflow-badge-failed",
  PENDING_CLEANUP: "workflow-badge-processing",
  PURGE_COMPLETE: "workflow-badge-purged",
};

export default function StatusBadge({ status }) {
  const className = STATUS_CLASS_MAP[status] || "workflow-badge-neutral";
  return <span className={`workflow-badge ${className}`}>{status}</span>;
}
