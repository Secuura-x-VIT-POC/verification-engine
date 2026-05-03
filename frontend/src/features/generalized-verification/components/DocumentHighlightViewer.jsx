import React, { useEffect, useRef, useState } from "react";
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
            <PageFrame
              key={pageNumber}
              pageNumber={pageNumber}
              pageHighlights={pageHighlights}
              activeCredentialId={activeCredentialId}
              onSelectCredential={onSelectCredential}
            />
          );
        })}
      </Document>
    </div>
  );
}

function PageFrame({
  pageNumber,
  pageHighlights,
  activeCredentialId,
  onSelectCredential,
}) {
  const frameRef = useRef(null);
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return undefined;
    const update = () => {
      const canvas = frame.querySelector("canvas");
      const target = canvas || frame;
      setPageSize({
        width: target.clientWidth || frame.clientWidth || 0,
        height: target.clientHeight || frame.clientHeight || 0,
      });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="gv-document-page">
      <div className="gv-document-page-meta">Page {pageNumber}</div>
      <div className="gv-document-page-frame" ref={frameRef}>
        <Page
          pageNumber={pageNumber}
          renderAnnotationLayer={false}
          renderTextLayer={false}
          onRenderSuccess={() => {
            const frame = frameRef.current;
            const canvas = frame?.querySelector("canvas");
            setPageSize({
              width: canvas?.clientWidth || frame?.clientWidth || 0,
              height: canvas?.clientHeight || frame?.clientHeight || 0,
            });
          }}
        />
        <HighlightOverlay
          highlightItems={pageHighlights}
          activeCredentialId={activeCredentialId}
          onSelectCredential={onSelectCredential}
          pageSize={pageSize}
        />
      </div>
    </div>
  );
}
