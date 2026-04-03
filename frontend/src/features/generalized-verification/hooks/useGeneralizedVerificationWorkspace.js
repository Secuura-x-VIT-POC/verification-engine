import { useEffect, useState } from "react";
import {
  getAnalysisStatus,
  getCredentialBundles,
  getCredentialAudits,
  getCredentials,
  getDocumentProfile,
  getSessionDocumentBlob,
  getSessionOverview,
  getVerificationExecutionStatus,
  getVerificationPlan,
  getVerificationTaskResults,
  getVerificationSummary,
} from "../api/generalizedVerificationApi.js";
import {
  createEmptyAnalysisStatus,
  createEmptyCredentialBundleCollection,
  createEmptyCredentialAuditCollection,
  createEmptyCredentialCollection,
  createEmptyDocumentProfile,
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
          getDocumentProfile(sessionId, token),
          getCredentials(sessionId, token),
          getVerificationPlan(sessionId, token),
          getVerificationTaskResults(sessionId, token),
          getCredentialBundles(sessionId, token),
          getCredentialAudits(sessionId, token),
          getVerificationSummary(sessionId, token),
          getAnalysisStatus(sessionId, token),
          getVerificationExecutionStatus(sessionId, token),
          session.document_available ? getSessionDocumentBlob(sessionId, token) : Promise.resolve(null),
        ];

        const [
          documentProfileResult,
          credentialsResult,
          verificationPlanResult,
          verificationTaskResultsResult,
          credentialBundlesResult,
          credentialAuditsResult,
          verificationSummaryResult,
          analysisStatusResult,
          executionStatusResult,
          documentBlobResult,
        ] = await Promise.allSettled(artifactRequests);

        if (!isActive) {
          return;
        }

        const warnings = [];
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
            documentProfile,
            credentials,
            verificationPlan,
            verificationTaskResults,
            credentialBundles,
            credentialAudits,
            verificationSummary,
            analysisStatus,
            executionStatus,
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
