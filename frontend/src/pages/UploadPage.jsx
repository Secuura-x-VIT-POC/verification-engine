import React, { startTransition, useState } from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { apiRequest } from "../lib/api";

export default function UploadPage({ auth, onLogout }) {
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState("Not Started");
  const [selectedFile, setSelectedFile] = useState(null);
  const [error, setError] = useState("");
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  async function handleCreateSession() {
    setError("");
    setIsCreatingSession(true);

    try {
      const response = await apiRequest("/sessions", {
        method: "POST",
        token: auth.token,
      });
      setSessionId(response.session_id);
      setStatus(response.status);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsCreatingSession(false);
    }
  }

  function handleFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    if (file.type !== "application/pdf") {
      setError("Only PDF files are allowed.");
      event.target.value = "";
      setSelectedFile(null);
      return;
    }

    const maxSize = 25 * 1024 * 1024;
    if (file.size > maxSize) {
      setError("File must be smaller than 25 MB.");
      event.target.value = "";
      setSelectedFile(null);
      return;
    }

    setError("");
    setSelectedFile(file);
  }

  async function handleUpload() {
    if (!sessionId) {
      setError("Create a session first.");
      return;
    }

    if (!selectedFile) {
      setError("Choose a PDF before uploading.");
      return;
    }

    setError("");
    setIsUploading(true);

    try {
      const tokenResponse = await apiRequest(`/sessions/${sessionId}/upload-token`, {
        method: "POST",
        token: auth.token,
      });

      const formData = new FormData();
      formData.append("token", tokenResponse.upload_token);
      formData.append("file", selectedFile);

      const uploadResponse = await apiRequest("/upload", {
        method: "POST",
        token: auth.token,
        body: formData,
      });

      setStatus(uploadResponse.status);
      startTransition(() => navigate(`/verify/${uploadResponse.session_id}`));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="page">
      <div className="app-header">
        <div>
          <p className="eyebrow">Reviewer workspace</p>
          <h1>Upload and verify</h1>
          <p className="muted">Signed in as {auth.username}</p>
        </div>
        <button type="button" className="secondary-btn" onClick={onLogout}>
          Logout
        </button>
      </div>

      <div className="card">
        <h2>Session Setup</h2>
        <p className="muted">
          Create a session, obtain a time-limited upload token, and store the PDF for review.
        </p>

        <div className="section action-row">
          <button
            type="button"
            className="primary-btn"
            onClick={handleCreateSession}
            disabled={isCreatingSession}
          >
            {isCreatingSession ? "Creating..." : "Create Session"}
          </button>
        </div>

        <div className="section status-grid">
          <p>
            <strong>Session ID:</strong> {sessionId || "Not created"}
          </p>
          <p>
            <strong>Status:</strong>{" "}
            {status === "Not Started" ? status : <StatusBadge status={status} />}
          </p>
        </div>

        <div className="section">
          <label htmlFor="pdf-upload">PDF document</label>
          <input
            id="pdf-upload"
            type="file"
            accept="application/pdf"
            onChange={handleFileChange}
          />
        </div>

        {selectedFile ? (
          <div className="section info-box">
            <p>
              <strong>File:</strong> {selectedFile.name}
            </p>
            <p>
              <strong>Size:</strong> {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        ) : null}

        {error ? <p className="error-text section">{error}</p> : null}

        <div className="section action-row">
          <button
            type="button"
            className="primary-btn"
            onClick={handleUpload}
            disabled={isUploading}
          >
            {isUploading ? "Uploading..." : "Upload PDF"}
          </button>
        </div>
      </div>
    </div>
  );
}
