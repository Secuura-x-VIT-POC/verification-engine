import React, { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import HighlightOverlay from "./HighlightOverlay";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

function buildPageNumbers(pageCount) {
  return Array.from({ length: pageCount }, (_, index) => index + 1);
}

export default function DocumentHighlightViewer({
  documentUrl,
  highlightItems,
  activeCredentialId,
  onSelectCredential,
}) {
  const [numPages, setNumPages] = useState(0);
  const [viewerError, setViewerError] = useState("");

  if (!documentUrl) {
    return <p className="muted">The PDF preview will appear here when a document is available.</p>;
  }

  const fallbackPageCount = Math.max(
    highlightItems.reduce((maxPage, item) => Math.max(maxPage, Number(item.page) || 1), 1),
    1
  );
  const pageCount = Math.max(numPages || fallbackPageCount, 1);

  return (
    <div className="gv-document-scroll">
      {viewerError ? <p className="error-text">{viewerError}</p> : null}
      <Document
        file={documentUrl}
        onLoadSuccess={({ numPages: loadedPageCount }) => {
          setNumPages(loadedPageCount);
          setViewerError("");
        }}
        onLoadError={() => setViewerError("Document preview could not be loaded for this session.")}
        loading={<p className="muted">Loading PDF preview...</p>}
      >
        {buildPageNumbers(pageCount).map((pageNumber) => {
          const pageHighlights = highlightItems.filter((item) => Number(item.page || 1) === pageNumber);

          return (
            <div key={pageNumber} className="gv-document-page">
              <div className="gv-document-page-meta">Page {pageNumber}</div>
              <div className="gv-document-page-frame">
                <Page
                  pageNumber={pageNumber}
                  renderAnnotationLayer={false}
                  renderTextLayer={false}
                />
                <HighlightOverlay
                  highlightItems={pageHighlights}
                  activeCredentialId={activeCredentialId}
                  onSelectCredential={onSelectCredential}
                />
              </div>
            </div>
          );
        })}
      </Document>
    </div>
  );
}
