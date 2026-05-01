from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher

from .models import BoundingBox, EvidenceLine, SpatialTextToken

EXACT_MATCH_CONFIDENCE = 0.99
FUZZY_MATCH_CONFIDENCE = 0.78
NO_MATCH_CONFIDENCE = 0.0
MIN_ACCEPTED_CONFIDENCE = 0.7


def ground_value_to_spatial_map(search_text: str, spatial_text_map: list[SpatialTextToken]) -> tuple[list[BoundingBox], float, str]:
    clean_target = _normalize_text(search_text)
    if not clean_target:
        return [], NO_MATCH_CONFIDENCE, "none"

    grouped_tokens: dict[int, list[SpatialTextToken]] = defaultdict(list)
    for token in spatial_text_map:
        grouped_tokens[token.page].append(token)

    best_boxes: list[BoundingBox] = []
    best_match_type = "none"
    best_similarity = 0.0

    for page_number, page_tokens in grouped_tokens.items():
        boxes, match_type, similarity = _find_best_match_on_page(clean_target, page_tokens, page_number)
        if similarity > best_similarity:
            best_similarity = similarity
            best_boxes = boxes
            best_match_type = match_type

    if best_match_type == "exact":
        return best_boxes, EXACT_MATCH_CONFIDENCE, "exact"
    if best_match_type == "fuzzy":
        return best_boxes, max(FUZZY_MATCH_CONFIDENCE, round(best_similarity, 4)), "fuzzy"
    return [], NO_MATCH_CONFIDENCE, "none"


def tokens_for_line(line: EvidenceLine, spatial_text_map: list[SpatialTextToken]) -> list[SpatialTextToken]:
    if line.token_indices:
        return [
            spatial_text_map[index]
            for index in line.token_indices
            if 0 <= index < len(spatial_text_map)
        ]
    return [
        token
        for token in spatial_text_map
        if token.page == line.page and _boxes_intersect(token.bbox, line.bbox)
    ]


def resolve_source_type(tokens: list[SpatialTextToken]) -> str:
    sources = [str(token.source or "native_text") for token in tokens]
    unique_sources = list(dict.fromkeys(source for source in sources if source))
    if not unique_sources:
        return "unknown"
    if len(unique_sources) == 1:
        return unique_sources[0]
    if "native_text" in unique_sources and any(source.startswith("ocr_") or source in {"paddleocr", "tesseract"} for source in unique_sources):
        return "merged_native_ocr"
    return "merged_ocr"


def average_token_confidence(tokens: list[SpatialTextToken], *, bounding_box: BoundingBox | None = None) -> float:
    scoped_tokens = list(tokens)
    if bounding_box is not None:
        scoped_tokens = [
            token
            for token in scoped_tokens
            if _boxes_intersect(token.bbox, bounding_box)
        ]
    if not scoped_tokens:
        return 0.0
    return round(sum(float(token.confidence or 0.0) for token in scoped_tokens) / len(scoped_tokens), 4)


def merge_bounding_boxes(boxes: list[BoundingBox | None]) -> BoundingBox | None:
    valid = [box for box in boxes if box is not None]
    if not valid:
        return None
    return BoundingBox(
        page=valid[0].page,
        x0=round(min(box.x0 for box in valid), 2),
        y0=round(min(box.y0 for box in valid), 2),
        x1=round(max(box.x1 for box in valid), 2),
        y1=round(max(box.y1 for box in valid), 2),
    )


def _find_best_match_on_page(target_text: str, page_tokens: list[SpatialTextToken], page_number: int) -> tuple[list[BoundingBox], str, float]:
    target_word_count = max(1, len(target_text.split()))
    max_window = min(len(page_tokens), target_word_count + 5)
    best_similarity = 0.0
    best_boxes: list[BoundingBox] = []
    best_match_type = "none"

    for start_index in range(len(page_tokens)):
        for window_size in range(1, max_window + 1):
            end_index = start_index + window_size
            if end_index > len(page_tokens):
                break
            token_slice = page_tokens[start_index:end_index]
            candidate_text = _normalize_text(" ".join(token.text for token in token_slice))
            if not candidate_text:
                continue
            if candidate_text == target_text:
                return [_merge_tokens_to_box(token_slice, page_number)], "exact", 1.0
            similarity = SequenceMatcher(None, target_text, candidate_text).ratio()
            if similarity >= 0.75 and similarity > best_similarity:
                best_similarity = similarity
                best_boxes = [_merge_tokens_to_box(token_slice, page_number)]
                best_match_type = "fuzzy"

    return best_boxes, best_match_type, best_similarity


def _merge_tokens_to_box(tokens: list[SpatialTextToken], page_number: int) -> BoundingBox:
    return BoundingBox(
        page=page_number,
        x0=round(min(float(token.bbox[0]) for token in tokens), 2),
        y0=round(min(float(token.bbox[1]) for token in tokens), 2),
        x1=round(max(float(token.bbox[2]) for token in tokens), 2),
        y1=round(max(float(token.bbox[3]) for token in tokens), 2),
    )


def _boxes_intersect(token_bbox: list[float], line_bbox: BoundingBox) -> bool:
    if len(token_bbox) < 4:
        return False
    x0, y0, x1, y1 = token_bbox[:4]
    return not (
        x1 < float(line_bbox.x0)
        or x0 > float(line_bbox.x1)
        or y1 < float(line_bbox.y0)
        or y0 > float(line_bbox.y1)
    )


def _normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    lowered = "".join(char if char.isalnum() or char.isspace() else " " for char in lowered)
    return " ".join(lowered.split())
