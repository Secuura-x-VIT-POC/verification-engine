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
  const scrollRef = useRef(null);
  const [numPages, setNumPages] = useState(0);
  const [viewerError, setViewerError] = useState("");
  const [renderWidth, setRenderWidth] = useState(820);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return undefined;
    const update = () => {
      const width = Math.floor(container.clientWidth || 820);
      setRenderWidth(Math.max(320, Math.min(width - 8, 1100)));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  if (!documentUrl) {
    return <p className="muted">The PDF preview will appear here when a document is available.</p>;
  }

  const fallbackPageCount = Math.max(
    highlightItems.reduce((maxPage, item) => Math.max(maxPage, Number(item.page) || 1), 1),
    1
  );
  const pageCount = Math.max(numPages || fallbackPageCount, 1);

  return (
    <div className="gv-document-scroll" ref={scrollRef}>
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
              renderWidth={renderWidth}
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
  renderWidth,
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
      <div
        className="gv-document-page-frame"
        ref={frameRef}
        style={{ width: `${renderWidth}px` }}
      >
        <Page
          pageNumber={pageNumber}
          width={renderWidth}
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
