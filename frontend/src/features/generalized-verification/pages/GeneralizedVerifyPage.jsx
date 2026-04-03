import React, { startTransition, useEffect, useState } from "react";
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

export default function GeneralizedVerifyPage({ auth, onLogout }) {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const workspace = useGeneralizedVerificationWorkspace({ sessionId, token: auth.token });
  const [activeTab, setActiveTab] = useState("document");
  const [selectedCredentialId, setSelectedCredentialId] = useState(null);

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
    providerCapabilities: workspace.data.providerCapabilities,
  });

  useEffect(() => {
    const selectableIds = [
      ...viewModel.highlightItems.map((item) => item.credentialId),
      ...viewModel.auditDetails.map((detail) => detail.credentialId),
    ];

    if (!selectableIds.length) {
      setSelectedCredentialId(null);
      return;
    }

    if (!selectedCredentialId || !selectableIds.includes(selectedCredentialId)) {
      setSelectedCredentialId(viewModel.selectedCredentialId);
    }
  }, [selectedCredentialId, viewModel.auditDetails, viewModel.highlightItems, viewModel.selectedCredentialId]);

  const selectedAuditDetail = getAuditDetailByCredentialId(viewModel.auditDetails, selectedCredentialId);

  return (
    <div className="page gv-page">
      <div className="app-header">
        <div>
          <p className="eyebrow">Generalized verification workspace</p>
          <h1>Session {workspace.data.session.session_id || sessionId}</h1>
          <p className="muted">Read-only reviewer workspace for document profile, routing, audits, and overlays.</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="secondary-btn"
            onClick={() => startTransition(() => navigate(getLegacyVerifyPath(sessionId)))}
          >
            Legacy Verify Page
          </button>
          <button type="button" className="secondary-btn" onClick={() => startTransition(() => navigate("/upload"))}>
            New Upload
          </button>
          <button type="button" className="secondary-btn" onClick={onLogout}>
            Logout
          </button>
        </div>
      </div>

      {workspace.isLoading ? <p className="muted">Loading generalized verification artifacts...</p> : null}
      {workspace.error ? (
        <div className="panel">
          <p className="error-text">{workspace.error}</p>
          <p className="muted">
            This workspace stays read-only and will not retry verification automatically. You can return to the legacy
            verify page if you need the existing verification flow.
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

          <div className="gv-workspace-layout">
            <WorkspaceLeftSidebar
              documentProfile={workspace.data.documentProfile}
              summaryStats={viewModel.summaryStats}
              statusCounts={viewModel.statusCounts}
              credentialItems={viewModel.credentialItems}
              selectedCredentialId={selectedCredentialId}
              onSelectCredential={setSelectedCredentialId}
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
                  highlightItems={viewModel.highlightItems}
                  selectedAuditDetail={selectedAuditDetail}
                  onSelectCredential={setSelectedCredentialId}
                  selectedCredentialId={selectedCredentialId}
                  documentMessage={viewModel.messages.document}
                />
              ) : null}

              {activeTab === "analysis" ? (
                <AnalysisTab rows={viewModel.analysisRows} emptyMessage={viewModel.messages.credentials} />
              ) : null}

              {activeTab === "audit" ? (
                <AuditTab auditDetails={viewModel.auditDetails} emptyMessage={viewModel.messages.audits} />
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
