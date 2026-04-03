import { useEffect, useState } from "react";
import {
  getAgentCredentialCandidates,
  getAgentDocumentUnderstanding,
  getAgentRouteRecommendations,
  getAgentRunStatus,
  getAnalysisStatus,
  getCredentialBundles,
  getCredentialAudits,
  getCredentials,
  getDocumentProfile,
  getProviderCapabilities,
  getProviderExecutionStatus,
  getProviderExecutionTraces,
  getSessionDocumentBlob,
  getSessionOverview,
  getVerificationExecutionStatus,
  getVerificationPlan,
  getVerificationTaskResults,
  getVerificationSummary,
} from "../api/generalizedVerificationApi.js";
import {
  createEmptyAgentCredentialCandidateCollection,
  createEmptyAgentDocumentUnderstanding,
  createEmptyAgentRouteRecommendationCollection,
  createEmptyAgentRunStatus,
  createEmptyAnalysisStatus,
  createEmptyCredentialBundleCollection,
  createEmptyCredentialAuditCollection,
  createEmptyCredentialCollection,
  createEmptyDocumentProfile,
  createEmptyProviderCapabilityCollection,
  createEmptyProviderExecutionStatus,
  createEmptyProviderExecutionTraceCollection,
  createEmptySessionOverview,
  createEmptyVerificationExecutionStatus,
  createEmptyVerificationPlan,
  createEmptyVerificationTaskResultCollection,
  createEmptyVerificationSummary,
} from "../types/contracts.js";

function createEmptyWorkspaceData(sessionId) {
  return {
    session: createEmptySessionOverview(sessionId),
    documentProfile: createEmptyDocumentProfile(sessionId),
    credentials: createEmptyCredentialCollection(sessionId),
    verificationPlan: createEmptyVerificationPlan(sessionId),
    verificationTaskResults: createEmptyVerificationTaskResultCollection(sessionId),
    credentialBundles: createEmptyCredentialBundleCollection(sessionId),
    credentialAudits: createEmptyCredentialAuditCollection(sessionId),
    verificationSummary: createEmptyVerificationSummary(sessionId),
    analysisStatus: createEmptyAnalysisStatus(sessionId),
    executionStatus: createEmptyVerificationExecutionStatus(sessionId),
    providerExecutionTraces: createEmptyProviderExecutionTraceCollection(sessionId),
    providerExecutionStatus: createEmptyProviderExecutionStatus(sessionId),
    providerCapabilities: createEmptyProviderCapabilityCollection(sessionId),
    agentDocumentUnderstanding: createEmptyAgentDocumentUnderstanding(sessionId),
    agentCredentialCandidates: createEmptyAgentCredentialCandidateCollection(sessionId),
    agentRouteRecommendations: createEmptyAgentRouteRecommendationCollection(sessionId),
    agentRunStatus: createEmptyAgentRunStatus(sessionId),
  };
}

function readSettledValue(result, fallbackValue, label, warnings) {
  if (result.status === "fulfilled") {
    return result.value;
  }

  warnings.push(`${label}: ${result.reason?.message || "Request failed"}`);
  return fallbackValue;
}

export function useGeneralizedVerificationWorkspace({ sessionId, token }) {
  const [state, setState] = useState(() => ({
    isLoading: true,
    error: "",
    warnings: [],
    documentUrl: "",
    data: createEmptyWorkspaceData(sessionId),
  }));

  useEffect(() => {
    let isActive = true;
    let nextObjectUrl = "";

    async function loadWorkspace() {
      setState({
        isLoading: true,
        error: "",
        warnings: [],
        documentUrl: "",
        data: createEmptyWorkspaceData(sessionId),
      });

      try {
        const session = await getSessionOverview(sessionId, token);
        if (!isActive) {
          return;
        }

        const artifactRequests = [
          getAgentDocumentUnderstanding(sessionId, token),
          getAgentCredentialCandidates(sessionId, token),
          getAgentRouteRecommendations(sessionId, token),
          getAgentRunStatus(sessionId, token),
          getDocumentProfile(sessionId, token),
          getCredentials(sessionId, token),
          getVerificationPlan(sessionId, token),
          getVerificationTaskResults(sessionId, token),
          getCredentialBundles(sessionId, token),
          getCredentialAudits(sessionId, token),
          getVerificationSummary(sessionId, token),
          getAnalysisStatus(sessionId, token),
          getVerificationExecutionStatus(sessionId, token),
          getProviderExecutionTraces(sessionId, token),
          getProviderExecutionStatus(sessionId, token),
          getProviderCapabilities(sessionId, token),
          session.document_available ? getSessionDocumentBlob(sessionId, token) : Promise.resolve(null),
        ];

        const [
          agentDocumentUnderstandingResult,
          agentCredentialCandidatesResult,
          agentRouteRecommendationsResult,
          agentRunStatusResult,
          documentProfileResult,
          credentialsResult,
          verificationPlanResult,
          verificationTaskResultsResult,
          credentialBundlesResult,
          credentialAuditsResult,
          verificationSummaryResult,
          analysisStatusResult,
          executionStatusResult,
          providerExecutionTracesResult,
          providerExecutionStatusResult,
          providerCapabilitiesResult,
          documentBlobResult,
        ] = await Promise.allSettled(artifactRequests);

        if (!isActive) {
          return;
        }

        const warnings = [];
        const agentDocumentUnderstanding = readSettledValue(
          agentDocumentUnderstandingResult,
          createEmptyAgentDocumentUnderstanding(sessionId),
          "Agent document understanding",
          warnings
        );
        const agentCredentialCandidates = readSettledValue(
          agentCredentialCandidatesResult,
          createEmptyAgentCredentialCandidateCollection(sessionId),
          "Agent credential candidates",
          warnings
        );
        const agentRouteRecommendations = readSettledValue(
          agentRouteRecommendationsResult,
          createEmptyAgentRouteRecommendationCollection(sessionId),
          "Agent route recommendations",
          warnings
        );
        const agentRunStatus = readSettledValue(
          agentRunStatusResult,
          createEmptyAgentRunStatus(sessionId),
          "Agent run status",
          warnings
        );
        const documentProfile = readSettledValue(
          documentProfileResult,
          createEmptyDocumentProfile(sessionId),
          "Document profile",
          warnings
        );
        const credentials = readSettledValue(
          credentialsResult,
          createEmptyCredentialCollection(sessionId),
          "Credentials",
          warnings
        );
        const verificationPlan = readSettledValue(
          verificationPlanResult,
          createEmptyVerificationPlan(sessionId),
          "Verification plan",
          warnings
        );
        const verificationTaskResults = readSettledValue(
          verificationTaskResultsResult,
          createEmptyVerificationTaskResultCollection(sessionId),
          "Verification task results",
          warnings
        );
        const credentialBundles = readSettledValue(
          credentialBundlesResult,
          createEmptyCredentialBundleCollection(sessionId),
          "Credential bundles",
          warnings
        );
        const credentialAudits = readSettledValue(
          credentialAuditsResult,
          createEmptyCredentialAuditCollection(sessionId),
          "Credential audits",
          warnings
        );
        const verificationSummary = readSettledValue(
          verificationSummaryResult,
          createEmptyVerificationSummary(sessionId),
          "Verification summary",
          warnings
        );
        const analysisStatus = readSettledValue(
          analysisStatusResult,
          createEmptyAnalysisStatus(sessionId),
          "Analysis status",
          warnings
        );
        const executionStatus = readSettledValue(
          executionStatusResult,
          createEmptyVerificationExecutionStatus(sessionId),
          "Execution status",
          warnings
        );
        const providerExecutionTraces = readSettledValue(
          providerExecutionTracesResult,
          createEmptyProviderExecutionTraceCollection(sessionId),
          "Provider execution traces",
          warnings
        );
        const providerExecutionStatus = readSettledValue(
          providerExecutionStatusResult,
          createEmptyProviderExecutionStatus(sessionId),
          "Provider execution status",
          warnings
        );
        const providerCapabilities = readSettledValue(
          providerCapabilitiesResult,
          createEmptyProviderCapabilityCollection(sessionId),
          "Provider capabilities",
          warnings
        );

        if (documentBlobResult.status === "fulfilled" && documentBlobResult.value) {
          nextObjectUrl = URL.createObjectURL(documentBlobResult.value);
        } else if (documentBlobResult.status === "rejected") {
          warnings.push(`Document preview: ${documentBlobResult.reason?.message || "Request failed"}`);
        }

        setState({
          isLoading: false,
          error: "",
          warnings,
          documentUrl: nextObjectUrl,
          data: {
            session,
            agentDocumentUnderstanding,
            agentCredentialCandidates,
            agentRouteRecommendations,
            agentRunStatus,
            documentProfile,
            credentials,
            verificationPlan,
            verificationTaskResults,
            credentialBundles,
            credentialAudits,
            verificationSummary,
            analysisStatus,
            executionStatus,
            providerExecutionTraces,
            providerExecutionStatus,
            providerCapabilities,
          },
        });
      } catch (requestError) {
        if (!isActive) {
          return;
        }

        setState({
          isLoading: false,
          error: requestError.message,
          warnings: [],
          documentUrl: "",
          data: createEmptyWorkspaceData(sessionId),
        });
      }
    }

    loadWorkspace();

    return () => {
      isActive = false;
      if (nextObjectUrl) {
        URL.revokeObjectURL(nextObjectUrl);
      }
    };
  }, [sessionId, token]);

  return state;
}
