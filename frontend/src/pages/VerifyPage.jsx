import React, { startTransition, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AuditReceiptPanel from "../audit_receipt/AuditReceiptPanel";
import StatusBadge from "../components/StatusBadge";
import { apiRequest } from "../lib/api";
import PdfViewer from "../pdf_viewer/PdfViewer";
import TrustPanel from "../trust_panel/TrustPanel";

export default function VerifyPage({ auth, onLogout }) {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [sessionData, setSessionData] = useState(null);
  const [documentUrl, setDocumentUrl] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isClosing, setIsClosing] = useState(false);

  useEffect(() => {
    let isActive = true;
    let objectUrl = "";

    async function loadWorkflow() {
      setIsLoading(true);
      setError("");

      try {
        const currentSession = await apiRequest(`/sessions/${sessionId}`, {
          token: auth.token,
        });

        if (!isActive) {
          return;
        }

        setSessionData(currentSession);

        if (currentSession.document_available) {
          const pdfBlob = await apiRequest(`/sessions/${sessionId}/document`, {
            token: auth.token,
          });
          objectUrl = URL.createObjectURL(pdfBlob);

          if (isActive) {
            setDocumentUrl(objectUrl);
          }
        }

        if (
          currentSession.status === "UPLOADED_PENDING_REVIEW" ||
          currentSession.status === "FAILED_RETRIABLE"
        ) {
          const verifiedSession = await apiRequest(`/session/${sessionId}/verify`, {
            method: "POST",
            token: auth.token,
          });

          if (isActive) {
            setSessionData(verifiedSession);
          }
        }
      } catch (requestError) {
        if (isActive) {
          setError(requestError.message);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    loadWorkflow();

    return () => {
      isActive = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [auth.token, sessionId]);

  async function handleRetryVerification() {
    setIsLoading(true);
    setError("");

    try {
      const verifiedSession = await apiRequest(`/session/${sessionId}/verify`, {
        method: "POST",
        token: auth.token,
      });
      setSessionData(verifiedSession);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCloseSession() {
    setIsClosing(true);
    setError("");

    try {
      await apiRequest(`/sessions/${sessionId}/close`, {
        method: "POST",
        token: auth.token,
      });
      startTransition(() => navigate("/upload"));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsClosing(false);
    }
  }

  const extraction = sessionData?.extraction;

  return (
    <div className="page">
      <div className="app-header">
        <div>
          <p className="eyebrow">Verification view</p>
          <h1>Session review</h1>
          <p className="muted">Signed in as {auth.username}</p>
        </div>
        <div className="header-actions">
          <button type="button" className="secondary-btn" onClick={() => navigate("/upload")}>
            New Upload
          </button>
          <button type="button" className="secondary-btn" onClick={onLogout}>
            Logout
          </button>
        </div>
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="verify-layout">
        <div className="left-column">
          <div className="panel">
            <h2>PDF Viewer</h2>
            <PdfViewer fileUrl={documentUrl} boxes={extraction?.bounding_boxes} />
          </div>
        </div>

        <div className="right-column">
          <div className="panel">
            <h2>Session</h2>
            <p>
              <strong>Session ID:</strong> {sessionId}
            </p>
            <p>
              <strong>Status:</strong>{" "}
              {sessionData ? <StatusBadge status={sessionData.status} /> : "Loading..."}
            </p>
            <p>
              <strong>Worker Phase:</strong> {sessionData?.worker_phase || "Waiting"}
            </p>
          </div>

          <div className="panel">
            <h2>Extraction</h2>
            {isLoading && !sessionData ? <p className="muted">Loading workflow...</p> : null}
            {!isLoading && !extraction ? (
              <p className="muted">No extraction payload is available yet.</p>
            ) : null}
            {extraction?.field_details?.length ? (
              <div className="field-list">
                {extraction.field_details.map((field) => (
                  <div key={field.key} className="field-row">
                    <p>
                      <strong>{field.label}:</strong> {field.value || "Not extracted"}
                    </p>
                    <p className="muted">
                      Confidence {field.confidence} | {field.is_grounded ? "Grounded" : "Not grounded"}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
            {extraction?.error_message ? <p className="error-text">{extraction.error_message}</p> : null}
          </div>

          <TrustPanel trust={sessionData?.trust} />
          <AuditReceiptPanel audit={sessionData?.audit} />

          <div className="panel">
            <div className="action-row">
              <button
                type="button"
                className="secondary-btn"
                onClick={handleRetryVerification}
                disabled={isLoading}
              >
                Retry Verification
              </button>
              <button
                type="button"
                className="primary-btn"
                onClick={handleCloseSession}
                disabled={isClosing}
              >
                {isClosing ? "Closing..." : "Close Session"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
