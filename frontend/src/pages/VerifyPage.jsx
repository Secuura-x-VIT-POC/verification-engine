import React from "react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import PdfViewer from "../pdf_viewer/PdfViewer";
import TrustPanel from "../trust_panel/TrustPanel";
import AuditReceiptPanel from "../audit_receipt/AuditReceiptPanel";

export default function VerifyPage({ loggedInUser }) {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [status, setStatus] = useState("PROCESSING");
  const [verificationData, setVerificationData] = useState(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVerificationData({
        extraction: {
          document_type: "transcript",
          ocr_used: false,
          fields: {
            name: "John Doe",
            institution: "VIT",
            credential: "B.Tech",
            date: "2025-05-01",
            id: "ABC123"
          },
          confidence: {
            name: 0.98,
            institution: 0.95,
            credential: 0.96,
            date: 0.93,
            id: 0.91
          },
          bounding_boxes: {
              name: { page: 1, x1: 95, y1: 135, x2: 220, y2: 165 },
              institution: { page: 1, x1: 95, y1: 205, x2: 150, y2: 235 }
          }
        },
        trust: {
          outcome: "GREEN",
          reason_codes: ["REGISTRY_MATCH", "GROUNDING_OK"],
          connector_ids: ["vit_registry_mock"]
        },
        audit: {
          audit_event_id: "uuid-demo-123",
          logger_name: loggedInUser || "Unknown User",
          document_commitment: "hmac_demo_value_abc123xyz",
          outcome: "GREEN",
          reason_codes: ["REGISTRY_MATCH"],
          issued_at: "2026-03-26T20:00:00Z"
        }
      });

      setStatus("VERIFIED");
    }, 1500);

    return () => clearTimeout(timer);
  }, []);

  function handleCloseSession() {
    setVerificationData(null);
    setStatus("PURGED");
    navigate("/");
  }

  return (
    <div className="page">
      <div className="verify-layout">
        <div className="left-column">
          <div className="panel">
            <h2>PDF Viewer</h2>
            <PdfViewer
              fileUrl="/sample.pdf"
              boxes={verificationData?.extraction?.bounding_boxes}
            /> 
          </div>
        </div>

        <div className="right-column">
          <div className="panel">
            <h2>Session</h2>
            <p>
              <strong>Session ID:</strong> {sessionId}
            </p>
            <p>
              <strong>Status:</strong> <StatusBadge status={status} />
            </p>
          </div>

          {verificationData?.extraction && (
            <div className="panel">
              <h2>Extracted Fields</h2>
              <p>
                <strong>Name:</strong> {verificationData.extraction.fields.name}
              </p>
              <p>
                <strong>Institution:</strong>{" "}
                {verificationData.extraction.fields.institution}
              </p>
              <p>
                <strong>Credential:</strong>{" "}
                {verificationData.extraction.fields.credential}
              </p>
              <p>
                <strong>Date:</strong> {verificationData.extraction.fields.date}
              </p>
              <p>
                <strong>ID:</strong> {verificationData.extraction.fields.id}
              </p>

              <hr />

              <p>
                <strong>Name Confidence:</strong>{" "}
                {verificationData.extraction.confidence.name}
              </p>
              <p>
                <strong>Institution Confidence:</strong>{" "}
                {verificationData.extraction.confidence.institution}
              </p>
            </div>
          )}

          <TrustPanel trust={verificationData?.trust} />
          <AuditReceiptPanel audit={verificationData?.audit} />

          <div className="panel">
            <button className="primary-btn" onClick={handleCloseSession}>
              Close Session
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}