export function buildHighlightStyle(item, pageSize) {
	if (item.relativeBox) {
		return {
			left: `${item.relativeBox.left}%`,
			top: `${item.relativeBox.top}%`,
			width: `${item.relativeBox.width}%`,
			height: `${item.relativeBox.height}%`,
		};
	}

	const box = item.absoluteBox;
	if (!box || item.coordinateSpace !== "pp_chatocr_image_pixels") {
		return {};
	}

	const renderedWidth = Number(pageSize?.width || 0);
	const renderedHeight = Number(pageSize?.height || 0);
	const sourceWidth = Number(item.sourceWidth || renderedWidth || 1);
	const sourceHeight = Number(item.sourceHeight || renderedHeight || 1);
	const scaleX = renderedWidth / sourceWidth;
	const scaleY = renderedHeight / sourceHeight;

	return {
		left: `${box.left * scaleX}px`,
		top: `${box.top * scaleY}px`,
		width: `${Math.max(1, box.width * scaleX)}px`,
		height: `${Math.max(1, box.height * scaleY)}px`,
	};
}
