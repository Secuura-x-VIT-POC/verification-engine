from collections import defaultdict
from typing import Iterable, List, Sequence

from extraction.schema.models import BoundingBox, SpatialTextToken

EXACT_MATCH_CONFIDENCE = 0.99
FUZZY_MATCH_CONFIDENCE = 0.70
NO_MATCH_CONFIDENCE = 0.0
MIN_ACCEPTED_CONFIDENCE = FUZZY_MATCH_CONFIDENCE


def ground_value_to_spatial_map(
    search_text: str,
    spatial_text_map: Sequence[SpatialTextToken | dict],
) -> tuple[list[BoundingBox], float, str]:
    clean_target = _normalize_text(search_text)
    if not clean_target:
        return [], NO_MATCH_CONFIDENCE, "none"

    tokens = [_coerce_token(token) for token in spatial_text_map]
    grouped_tokens = defaultdict(list)
    for token in tokens:
        grouped_tokens[token.page].append(token)

    best_match_boxes: list[BoundingBox] = []
    best_match_type = "none"
    best_similarity = 0.0

    for page_number, page_tokens in grouped_tokens.items():
        candidate_boxes, match_type, similarity = _find_best_match_on_page(clean_target, page_tokens, page_number)
        if similarity > best_similarity:
            best_similarity = similarity
            best_match_boxes = candidate_boxes
            best_match_type = match_type

    if best_match_type == "exact":
        return best_match_boxes, EXACT_MATCH_CONFIDENCE, "exact"
    if best_match_type == "fuzzy":
        return best_match_boxes, FUZZY_MATCH_CONFIDENCE, "fuzzy"
    return [], NO_MATCH_CONFIDENCE, "none"


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

            distance = _levenshtein_distance(target_text, candidate_text)
            similarity = 1.0 - (distance / max(len(target_text), len(candidate_text), 1))
            if candidate_text == target_text:
                return [_merge_tokens_to_box(token_slice, page_number)], "exact", 1.0

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
    x0 = min(token.bbox[0] for token in token_list)
    y0 = min(token.bbox[1] for token in token_list)
    x1 = max(token.bbox[2] for token in token_list)
    y1 = max(token.bbox[3] for token in token_list)
    return BoundingBox(
        page=page_number,
        x0=round(x0, 2),
        y0=round(y0, 2),
        x1=round(x1, 2),
        y1=round(y1, 2),
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
