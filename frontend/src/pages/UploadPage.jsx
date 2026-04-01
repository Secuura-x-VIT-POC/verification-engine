import React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";

export default function UploadPage() {
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState("Not Started");
  const [selectedFile, setSelectedFile] = useState(null);

  function handleCreateSession() {
    const id = "sess_" + Math.random().toString(36).slice(2, 10);
    setSessionId(id);
    setStatus("CREATED");
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.type !== "application/pdf") {
      alert("Only PDF files are allowed.");
      e.target.value = "";
      setSelectedFile(null);
      return;
    }

    const maxSize = 25 * 1024 * 1024;
    if (file.size > maxSize) {
      alert("File must be smaller than 25 MB.");
      e.target.value = "";
      setSelectedFile(null);
      return;
    }

    setSelectedFile(file);
  }

  function handleUpload() {
    if (!sessionId) {
      alert("Create a session first.");
      return;
    }

    if (!selectedFile) {
      alert("Please choose a PDF first.");
      return;
    }

    setStatus("UPLOADED");
    navigate(`/verify/${sessionId}`);
  }

  return (
    <div className="page">
      <div className="card">
        <h1>Upload PDF</h1>
        <p className="muted">Create a session, choose a PDF, then upload it.</p>

        <div className="section">
          <button className="primary-btn" onClick={handleCreateSession}>
            Create Session
          </button>
        </div>

        <div className="section">
          <p>
            <strong>Session ID:</strong> {sessionId || "Not created"}
          </p>
          <p>
            <strong>Status:</strong>{" "}
            {status === "Not Started" ? status : <StatusBadge status={status} />}
          </p>
        </div>

        <div className="section">
          <label htmlFor="pdf-upload">Select PDF</label>
          <input
            id="pdf-upload"
            type="file"
            accept="application/pdf"
            onChange={handleFileChange}
          />
        </div>

        {selectedFile && (
          <div className="section info-box">
            <p>
              <strong>File:</strong> {selectedFile.name}
            </p>
            <p>
              <strong>Size:</strong>{" "}
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        )}

        <div className="section">
          <button className="primary-btn" onClick={handleUpload}>
            Upload PDF
          </button>
        </div>
      </div>
    </div>
  );
}