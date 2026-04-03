import React from "react";

export default function HighlightOverlay({ boxes, pageWidth, pageHeight }) {
  if (!boxes || !pageWidth || !pageHeight) {
    return null;
  }

  const normalizedBoxes = Array.isArray(boxes)
    ? boxes
    : Object.entries(boxes).map(([key, box]) => ({
        key,
        ...box,
      }));

  return (
    <>
      {normalizedBoxes.map((box) => {
        const x0 = box.x0 ?? box.x1 ?? 0;
        const y0 = box.y0 ?? box.y1 ?? 0;
        const x1 = box.x1 ?? box.x2 ?? 0;
        const y1 = box.y1 ?? box.y2 ?? 0;

        return (
          <div
            key={box.key}
            className="highlight-box"
            style={{
              left: `${x0}px`,
              top: `${y0}px`,
              width: `${Math.max(x1 - x0, 0)}px`,
              height: `${Math.max(y1 - y0, 0)}px`,
            }}
            title={box.key}
          />
        );
      })}
    </>
  );
}