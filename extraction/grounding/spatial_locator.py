from __future__ import annotations

from collections import defaultdict
from typing import Iterable, List, Sequence

import fitz

from extraction.schema.models import BoundingBox, EvidenceLine, SpatialTextToken

EXACT_MATCH_CONFIDENCE = 0.99
FUZZY_MATCH_CONFIDENCE = 0.7
NO_MATCH_CONFIDENCE = 0.0
MIN_ACCEPTED_CONFIDENCE = FUZZY_MATCH_CONFIDENCE


def find_bounding_boxes(doc: fitz.Document, search_text: str) -> List[BoundingBox]:
    boxes: List[BoundingBox] = []
    clean_text = " ".join(search_text.split())
    if not clean_text:
        return boxes

    for page_num in range(len(doc)):
        page = doc[page_num]
        for inst in page.search_for(clean_text):
            boxes.append(
                BoundingBox(
                    page=page_num + 1,
                    x0=round(inst.x0, 2),
                    y0=round(inst.y0, 2),
                    x1=round(inst.x1, 2),
                    y1=round(inst.y1, 2),
                )
            )
    return boxes


def ground_value_to_spatial_map(
    search_text: str,
    spatial_text_map: Sequence[SpatialTextToken | dict],
) -> tuple[list[BoundingBox], float, str]:
    clean_target = _normalize_text(search_text)
    if not clean_target:
        return [], NO_MATCH_CONFIDENCE, "none"

    grouped_tokens = defaultdict(list)
    for token in (_coerce_token(entry) for entry in spatial_text_map):
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
        return best_boxes, FUZZY_MATCH_CONFIDENCE, "fuzzy"
    return [], NO_MATCH_CONFIDENCE, "none"


def tokens_for_line(
    line: EvidenceLine | dict,
    spatial_text_map: Sequence[SpatialTextToken | dict],
) -> list[SpatialTextToken]:
    evidence_line = line if isinstance(line, EvidenceLine) else EvidenceLine.model_validate(line)
    coerced_tokens = [_coerce_token(entry) for entry in spatial_text_map]
    if evidence_line.token_indices:
        return [
            coerced_tokens[index]
            for index in evidence_line.token_indices
            if 0 <= index < len(coerced_tokens)
        ]

    page_tokens = [token for token in coerced_tokens if token.page == evidence_line.page]
    if evidence_line.bbox is None:
        return page_tokens
    return [
        token
        for token in page_tokens
        if _boxes_intersect(token.bbox, evidence_line.bbox)
    ]


def resolve_source_type(tokens: Sequence[SpatialTextToken | dict]) -> str:
    sources = [str(_coerce_token(token).source or "native_text") for token in tokens]
    unique_sources = list(dict.fromkeys(source for source in sources if source))
    if not unique_sources:
        return "unknown"
    if len(unique_sources) == 1:
        return unique_sources[0]
    if "native_text" in unique_sources and any(source.startswith("ocr_") for source in unique_sources):
        return "merged_native_ocr"
    return "merged_ocr"


def average_token_confidence(
    tokens: Sequence[SpatialTextToken | dict],
    *,
    bounding_box: BoundingBox | None = None,
) -> float:
    scoped_tokens = [_coerce_token(token) for token in tokens]
    if bounding_box is not None:
        scoped_tokens = [
            token
            for token in scoped_tokens
            if _boxes_intersect(token.bbox, bounding_box)
        ]
    if not scoped_tokens:
        return 0.0
    return round(sum(float(token.confidence or 0.0) for token in scoped_tokens) / len(scoped_tokens), 4)


def merge_bounding_boxes(boxes: Sequence[BoundingBox | None]) -> BoundingBox | None:
    valid_boxes = [box for box in boxes if box is not None]
    if not valid_boxes:
        return None
    page = valid_boxes[0].page
    return BoundingBox(
        page=page,
        x0=round(min(box.x0 for box in valid_boxes), 2),
        y0=round(min(box.y0 for box in valid_boxes), 2),
        x1=round(max(box.x1 for box in valid_boxes), 2),
        y1=round(max(box.y1 for box in valid_boxes), 2),
    )


def _find_best_match_on_page(
    target_text: str,
    page_tokens: Sequence[SpatialTextToken],
    page_number: int,
) -> tuple[list[BoundingBox], str, float]:
    target_word_count = max(1, len(target_text.split()))
    max_window = min(len(page_tokens), target_word_count + 4)
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

            distance = _levenshtein_distance(target_text, candidate_text)
            similarity = 1.0 - (distance / max(len(target_text), len(candidate_text), 1))
            if similarity >= 0.75 and similarity > best_similarity:
                best_similarity = similarity
                best_boxes = [_merge_tokens_to_box(token_slice, page_number)]
                best_match_type = "fuzzy"

    return best_boxes, best_match_type, best_similarity


def _coerce_token(token: SpatialTextToken | dict) -> SpatialTextToken:
    if isinstance(token, SpatialTextToken):
        return token
    return SpatialTextToken.model_validate(token)


def _merge_tokens_to_box(tokens: Iterable[SpatialTextToken], page_number: int) -> BoundingBox:
    token_list = list(tokens)
    return BoundingBox(
        page=page_number,
        x0=round(min(token.bbox[0] for token in token_list), 2),
        y0=round(min(token.bbox[1] for token in token_list), 2),
        x1=round(max(token.bbox[2] for token in token_list), 2),
        y1=round(max(token.bbox[3] for token in token_list), 2),
    )


def _boxes_intersect(token_bbox: Sequence[float], line_bbox: BoundingBox) -> bool:
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


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current_row = [i]
        for j, right_char in enumerate(right, start=1):
            insertion = current_row[j - 1] + 1
            deletion = previous_row[j] + 1
            substitution = previous_row[j - 1] + (0 if left_char == right_char else 1)
            current_row.append(min(insertion, deletion, substitution))
        previous_row = current_row
    return previous_row[-1]
