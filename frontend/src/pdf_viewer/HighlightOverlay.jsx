import React from "react";

export default function HighlightOverlay({ boxes, pageWidth, pageHeight }) {
  if (!boxes || !pageWidth || !pageHeight) {
    return null;
  }

  const scaleX = pageWidth / 600;
  const scaleY = pageHeight / 800;
  const normalizedBoxes = Array.isArray(boxes) ? boxes : Object.entries(boxes);

  return (
    <>
      {normalizedBoxes.map((entry) => {
        const [key, box] = Array.isArray(entry) ? entry : [entry.key, entry];
        const x0 = box.x0 ?? box.x1 ?? 0;
        const y0 = box.y0 ?? box.y1 ?? 0;
        const x1 = box.x1 ?? box.x2 ?? 0;
        const y1 = box.y1 ?? box.y2 ?? 0;

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
