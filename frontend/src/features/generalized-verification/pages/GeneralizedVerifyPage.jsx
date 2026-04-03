import React, { startTransition, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getGeneralizedVerifyPath, getLegacyVerifyPath } from "../../../routes/paths";
import { useGeneralizedVerificationWorkspace } from "../hooks/useGeneralizedVerificationWorkspace";
import {
  buildWorkspaceViewModel,
  getAuditDetailByCredentialId,
} from "../utils/viewModels";
import AnalysisTab from "../components/AnalysisTab";
import AuditTab from "../components/AuditTab";
import DocumentTab from "../components/DocumentTab";
import WorkspaceLeftSidebar from "../components/WorkspaceLeftSidebar";
import WorkspaceRightSidebar from "../components/WorkspaceRightSidebar";
import WorkspaceTabNav from "../components/WorkspaceTabNav";
import "../generalizedVerification.css";

function matchesFilters(item, filters) {
  if (!item) return false;

  if (filters.status !== "ALL") {
    const itemStatus = item.auditStatus || "UNVERIFIED";
    if (itemStatus !== filters.status) {
      return false;
    }
  }

  if (filters.category !== "ALL") {
    const itemCategory = item.category || "UNCATEGORIZED";
    if (itemCategory !== filters.category) {
      return false;
    }
  }

  if (filters.piiOnly && !item.isPii && !item.pii) {
    return false;
  }

  if (filters.manualReviewOnly) {
    const needsManualReview =
      item.auditStatus === "MANUAL_REVIEW" ||
      item.agentManualReviewRecommended ||
      item.manualReviewRecommended ||
      item.requiresManualReview;
    if (!needsManualReview) {
      return false;
    }
  }

  return true;
}

export default function GeneralizedVerifyPage({ auth, onLogout }) {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const workspace = useGeneralizedVerificationWorkspace({ sessionId, token: auth.token });

  const [activeTab, setActiveTab] = useState("document");
  const [selectedCredentialId, setSelectedCredentialId] = useState(null);
  const [filters, setFilters] = useState({
    status: "ALL",
    category: "ALL",
    piiOnly: false,
    manualReviewOnly: false,
  });

  const viewModel = buildWorkspaceViewModel({
    session: workspace.data.session,
    agentDocumentUnderstanding: workspace.data.agentDocumentUnderstanding,
    agentCredentialCandidates: workspace.data.agentCredentialCandidates,
    agentRouteRecommendations: workspace.data.agentRouteRecommendations,
    agentRunStatus: workspace.data.agentRunStatus,
    documentProfile: workspace.data.documentProfile,
    credentials: workspace.data.credentials,
    verificationPlan: workspace.data.verificationPlan,
    verificationTaskResults: workspace.data.verificationTaskResults,
    credentialBundles: workspace.data.credentialBundles,
    credentialAudits: workspace.data.credentialAudits,
    verificationSummary: workspace.data.verificationSummary,
    analysisStatus: workspace.data.analysisStatus,
    executionStatus: workspace.data.executionStatus,
    providerExecutionTraces: workspace.data.providerExecutionTraces,
    providerExecutionStatus: workspace.data.providerExecutionStatus,
    providerOperatingMode: workspace.data.providerOperatingMode,
    providerCapabilities: workspace.data.providerCapabilities,
    demoProfile: workspace.data.demoProfile,
  });

  const availableCategories = useMemo(() => {
    const rawCategories = (viewModel.analysisRows || [])
      .map((row) => row.category)
      .filter(Boolean);
    return Array.from(new Set(rawCategories)).sort((a, b) => a.localeCompare(b));
  }, [viewModel.analysisRows]);

  const filteredCredentialItems = useMemo(
    () => viewModel.credentialItems.filter((item) => matchesFilters(item, filters)),
    [viewModel.credentialItems, filters]
  );

  const filteredAnalysisRows = useMemo(
    () => viewModel.analysisRows.filter((row) => matchesFilters(row, filters)),
    [viewModel.analysisRows, filters]
  );

  const filteredAuditDetails = useMemo(
    () => viewModel.auditDetails.filter((detail) => matchesFilters(detail, filters)),
    [viewModel.auditDetails, filters]
  );

  const filteredHighlightItems = useMemo(
    () =>
      viewModel.highlightItems.filter((item) => {
        const matchingAudit = viewModel.auditDetails.find(
          (detail) => detail.credentialId === item.credentialId
        );
        const matchingAnalysis = viewModel.analysisRows.find(
          (row) => row.credentialId === item.credentialId
        );
        return matchesFilters(
          {
            ...matchingAudit,
            ...matchingAnalysis,
            ...item,
            category: matchingAudit?.category || matchingAnalysis?.category,
          },
          filters
        );
      }),
    [viewModel.highlightItems, viewModel.auditDetails, viewModel.analysisRows, filters]
  );

  useEffect(() => {
    const selectableIds = [
      ...filteredHighlightItems.map((item) => item.credentialId),
      ...filteredAuditDetails.map((detail) => detail.credentialId),
    ];

    if (!selectableIds.length) {
      setSelectedCredentialId(null);
      return;
    }

    if (!selectedCredentialId || !selectableIds.includes(selectedCredentialId)) {
      setSelectedCredentialId(selectableIds[0]);
    }
  }, [selectedCredentialId, filteredAuditDetails, filteredHighlightItems]);

  const selectedAuditDetail = getAuditDetailByCredentialId(
    filteredAuditDetails,
    selectedCredentialId
  );

  return (
    <div className="page gv-page">
      <div className="app-header">
        <div>
          <p className="eyebrow">Generalized verification workspace</p>
          <h1>Session {workspace.data.session.session_id || sessionId}</h1>
          <p className="muted">
            Read-only reviewer workspace for document profile, routing, audits, and overlays.
          </p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="secondary-btn"
            onClick={() => startTransition(() => navigate(getLegacyVerifyPath(sessionId)))}
          >
            Legacy Verify Page
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => startTransition(() => navigate("/upload"))}
          >
            New Upload
          </button>
          <button type="button" className="secondary-btn" onClick={onLogout}>
            Logout
          </button>
        </div>
      </div>

      {workspace.isLoading ? (
        <p className="muted">Loading generalized verification artifacts...</p>
      ) : null}

      {workspace.error ? (
        <div className="panel">
          <p className="error-text">{workspace.error}</p>
          <p className="muted">
            This workspace stays read-only and will not retry verification automatically. You can
            return to the legacy verify page if you need the existing verification flow.
          </p>
          <div className="action-row">
            <button
              type="button"
              className="secondary-btn"
              onClick={() => startTransition(() => navigate(getLegacyVerifyPath(sessionId)))}
            >
              Open Legacy Flow
            </button>
          </div>
        </div>
      ) : (
        <>
          {viewModel.messages.analysis ? (
            <div className="panel gv-info-banner">
              <p>{viewModel.messages.analysis}</p>
            </div>
          ) : null}

          {viewModel.messages.agent ? (
            <div className="panel gv-info-banner">
              <p>{viewModel.messages.agent}</p>
            </div>
          ) : null}

          {viewModel.messages.provider ? (
            <div className="panel gv-info-banner">
              <p>{viewModel.messages.provider}</p>
            </div>
          ) : null}

          {viewModel.messages.providerMode ? (
            <div className="panel gv-info-banner">
              <p>{viewModel.messages.providerMode}</p>
            </div>
          ) : null}

          <div className="gv-workspace-layout">
            <WorkspaceLeftSidebar
              documentProfile={workspace.data.documentProfile}
              summaryStats={viewModel.summaryStats}
              statusCounts={viewModel.statusCounts}
              credentialItems={filteredCredentialItems}
              selectedCredentialId={selectedCredentialId}
              onSelectCredential={setSelectedCredentialId}
              filters={filters}
              onChangeFilters={setFilters}
              availableCategories={availableCategories}
            />

            <main className="gv-main-column">
              <div className="panel">
                <div className="gv-workspace-meta">
                  <div>
                    <span className="gv-detail-key">Workspace route</span>
                    <p>{getGeneralizedVerifyPath(sessionId)}</p>
                  </div>
                  <div>
                    <span className="gv-detail-key">File</span>
                    <p>{workspace.data.session.filename || "No file available"}</p>
                  </div>
                </div>
              </div>

              <WorkspaceTabNav activeTab={activeTab} onChange={setActiveTab} />

              {activeTab === "document" ? (
                <DocumentTab
                  documentUrl={workspace.documentUrl}
                  highlightItems={filteredHighlightItems}
                  selectedAuditDetail={selectedAuditDetail}
                  onSelectCredential={setSelectedCredentialId}
                  selectedCredentialId={selectedCredentialId}
                  documentMessage={viewModel.messages.document}
                />
              ) : null}

              {activeTab === "analysis" ? (
                <AnalysisTab
                  rows={filteredAnalysisRows}
                  emptyMessage={viewModel.messages.credentials}
                />
              ) : null}

              {activeTab === "audit" ? (
                <AuditTab
                  auditDetails={filteredAuditDetails}
                  emptyMessage={viewModel.messages.audits}
                />
              ) : null}
            </main>

            <WorkspaceRightSidebar
              session={workspace.data.session}
              analysisStatusLabel={viewModel.analysisStatusLabel}
              analysisStatus={workspace.data.analysisStatus}
              agentStatusLabel={viewModel.agentStatusLabel}
              agentUnderstandingSummary={viewModel.agentUnderstandingSummary}
              executionStatusLabel={viewModel.executionStatusLabel}
              executionStatus={workspace.data.executionStatus}
              providerExecutionStatusLabel={viewModel.providerExecutionStatusLabel}
              providerExecutionStatus={workspace.data.providerExecutionStatus}
              providerExecutionSummary={viewModel.providerExecutionSummary}
              providerOperatingMode={workspace.data.providerOperatingMode}
              demoProfile={workspace.data.demoProfile}
              taskExecutionSummary={viewModel.taskExecutionSummary}
              routingSummary={viewModel.routingSummary}
              verificationSummary={workspace.data.verificationSummary}
              overallOutcome={viewModel.overallOutcome}
              warnings={workspace.warnings}
            />
          </div>
        </>
      )}
    </div>
  );
}