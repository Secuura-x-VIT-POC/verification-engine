import React from "react";

export default function HighlightOverlay({
  boxes,
  pageWidth,
  pageHeight
}) {
  if (!boxes || !pageWidth || !pageHeight) return null;

  const baseWidth = 600;
  const baseHeight = 800;

  const scaleX = pageWidth / baseWidth;
  const scaleY = pageHeight / baseHeight;

  return (
    <>
      {Object.entries(boxes).map(([key, box]) => {
        const left = box.x1 * scaleX;
        const top = box.y1 * scaleY;
        const width = (box.x2 - box.x1) * scaleX;
        const height = (box.y2 - box.y1) * scaleY;

        return (
          <div
            key={key}
            className="highlight-box"
            style={{
              left: `${left}px`,
              top: `${top}px`,
              width: `${width}px`,
              height: `${height}px`
            }}
            title={key}
          />
        );
      })}
    </>
  );
}