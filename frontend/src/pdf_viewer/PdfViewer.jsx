import React, { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import HighlightOverlay from "./HighlightOverlay";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

export default function PdfViewer({ fileUrl = "/sample.pdf", boxes }) {
  const [numPages, setNumPages] = useState(0);
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 });

  function onDocumentLoadSuccess({ numPages }) {
    setNumPages(numPages);
  }

  function onPageLoadSuccess(page) {
    const viewport = page.getViewport({ scale: 1 });
    setPageSize({
      width: viewport.width,
      height: viewport.height
    });
  }

  return (
    <div className="pdf-wrapper">
      <div
        className="pdf-page-container"
        style={{
          width: pageSize.width ? `${pageSize.width}px` : "fit-content",
          height: pageSize.height ? `${pageSize.height}px` : "fit-content"
        }}
      >
        <Document file={fileUrl} onLoadSuccess={onDocumentLoadSuccess}>
          <Page
            pageNumber={1}
            onLoadSuccess={onPageLoadSuccess}
            renderTextLayer={false}
            renderAnnotationLayer={false}
          />
        </Document>

        <div className="overlay-layer">
          <HighlightOverlay
            boxes={boxes}
            pageWidth={pageSize.width}
            pageHeight={pageSize.height}
          />
        </div>
      </div>

      {numPages > 1 && (
        <p className="muted" style={{ marginTop: "12px" }}>
          Showing page 1 of {numPages}
        </p>
      )}
    </div>
  );
}