from __future__ import annotations

import hashlib
import re
from typing import Any


COORDINATE_SPACE = "pp_chatocr_image_pixels"


def build_evidence_graph_from_pp_chatocr(pp_payload: dict[str, Any]) -> dict[str, Any]:
    """Build sanitized, addressable evidence nodes from PP-ChatOCR output only."""
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, token in enumerate(list(pp_payload.get("spatial_text_map") or []), start=1):
        _append_evidence(
            evidence,
            seen,
            token,
            source_type="token" if str(token.get("source_kind") or "") != "seal" else "seal",
            fallback_id=f"pp-token-{index}",
            reading_order=index,
        )

    offset = len(evidence)
    for index, line in enumerate(list(pp_payload.get("evidence_lines") or []), start=1):
        _append_evidence(
            evidence,
            seen,
            line,
            source_type="line",
            fallback_id=str(line.get("evidence_line_id") or f"pp-line-{index}"),
            reading_order=offset + index,
        )

    offset = len(evidence)
    for index, block in enumerate(list(pp_payload.get("layout_blocks") or []), start=1):
        _append_evidence(
            evidence,
            seen,
            block,
            source_type="layout_block",
            fallback_id=str(block.get("layout_block_id") or f"pp-layout-{index}"),
            reading_order=offset + index,
        )

    offset = len(evidence)
    for index, cell in enumerate(list(pp_payload.get("table_cells") or []), start=1):
        _append_evidence(
            evidence,
            seen,
            cell,
            source_type="table_cell",
            fallback_id=str(cell.get("table_cell_id") or f"pp-table-cell-{index}"),
            reading_order=offset + index,
            row_index=cell.get("row_index"),
            column_index=cell.get("column_index"),
        )

    page_count = int(pp_payload.get("page_count") or max([1, *[int(item.get("page_number") or 1) for item in evidence]]))
    return {
        "source": "pp_chatocr_v4",
        "coordinate_space": COORDINATE_SPACE,
        "page_count": page_count,
        "evidence": evidence,
    }


def _append_evidence(
    evidence: list[dict[str, Any]],
    seen: set[str],
    item: dict[str, Any],
    *,
    source_type: str,
    fallback_id: str,
    reading_order: int,
    row_index: Any = None,
    column_index: Any = None,
) -> None:
    text_preview = _sanitize_preview(item.get("text_preview") or item.get("text") or item.get("block_content") or "")
    bbox = _coerce_bbox(item.get("bbox"))
    polygon = _coerce_polygon(item.get("polygon"))
    if not text_preview and not bbox and not polygon:
        return

    evidence_id = _stable_evidence_id(fallback_id, item, source_type)
    if evidence_id in seen:
        return
    seen.add(evidence_id)

    source_width = item.get("source_width") or item.get("width")
    source_height = item.get("source_height") or item.get("height")
    payload = {
        "evidence_id": evidence_id,
        "page_number": int(item.get("page_number") or item.get("page") or 1),
        "text_preview": text_preview,
        "source_type": source_type,
        "bbox": bbox,
        "polygon": polygon,
        "confidence": _coerce_float(item.get("confidence")),
        "reading_order": int(item.get("reading_order") or reading_order),
        "coordinate_space": item.get("coordinate_space") or COORDINATE_SPACE,
        "source_width": _coerce_float(source_width),
        "source_height": _coerce_float(source_height),
        "source": "pp_chatocr_v4",
    }
    if row_index is not None:
        payload["row_index"] = row_index
    if column_index is not None:
        payload["column_index"] = column_index
    evidence.append(payload)


def _stable_evidence_id(fallback_id: str, item: dict[str, Any], source_type: str) -> str:
    if item.get("evidence_id"):
        return str(item["evidence_id"])
    raw = f"{fallback_id}:{source_type}:{item.get('page_number') or item.get('page')}:{item.get('bbox')}:{item.get('text_preview') or item.get('text')}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"pp-{source_type}-{digest}"


def _sanitize_preview(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:160]


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _coerce_bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("bbox") or [value.get("x0"), value.get("y0"), value.get("x1"), value.get("y1")]
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            x0, y0, x1, y1 = [float(part) for part in value[:4]]
            return [round(min(x0, x1), 2), round(min(y0, y1), 2), round(max(x0, x1), 2), round(max(y0, y1), 2)]
        except (TypeError, ValueError):
            return None
    return None


def _coerce_polygon(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return None
    points: list[list[float]] = []
    for point in value:
        if hasattr(point, "tolist"):
            point = point.tolist()
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append([round(float(point[0]), 2), round(float(point[1]), 2)])
            except (TypeError, ValueError):
                continue
    return points or None
