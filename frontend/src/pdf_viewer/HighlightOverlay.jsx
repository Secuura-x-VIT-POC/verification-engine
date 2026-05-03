import React from "react";

export default function HighlightOverlay({ boxes, pageWidth, pageHeight }) {
  if (!boxes || !pageWidth || !pageHeight) {
    return null;
  }

  const normalizedBoxes = Array.isArray(boxes) ? boxes : Object.entries(boxes);

  return (
    <>
      {normalizedBoxes.map((entry) => {
        const [key, box] = Array.isArray(entry) ? entry : [entry.key, entry];
        const x0 = box.x0 ?? box.x1 ?? 0;
        const y0 = box.y0 ?? box.y1 ?? 0;
        const x1 = box.x1 ?? box.x2 ?? 0;
        const y1 = box.y1 ?? box.y2 ?? 0;
        const sourceWidth = Number(box.source_width || box.sourceWidth || pageWidth || 1);
        const sourceHeight = Number(box.source_height || box.sourceHeight || pageHeight || 1);
        const scaleX = pageWidth / sourceWidth;
        const scaleY = pageHeight / sourceHeight;

        return (
          <div
            key={key}
            className="highlight-box"
            style={{
              left: `${x0 * scaleX}px`,
              top: `${y0 * scaleY}px`,
              width: `${Math.max(x1 - x0, 0) * scaleX}px`,
              height: `${Math.max(y1 - y0, 0) * scaleY}px`,
            }}
            title={key}
          />
        );
      })}
    </>
  );
}
