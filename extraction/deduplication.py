from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import FieldCandidate


def fuzzy_deduplicate(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    kept: list[FieldCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.confidence, item.page, item.label)):
        duplicate_index = _find_duplicate_index(kept, candidate)
        if duplicate_index is None:
            kept.append(candidate.model_copy(deep=True))
            continue
        kept[duplicate_index] = _merge_candidates(kept[duplicate_index], candidate)
    return kept


def _find_duplicate_index(kept: list[FieldCandidate], candidate: FieldCandidate) -> int | None:
    label = candidate.label.strip().lower()
    value = _normalize_value(candidate.normalized_value or candidate.raw_value or "")
    for index, existing in enumerate(kept):
        if existing.page != candidate.page:
            continue
        existing_value = _normalize_value(existing.normalized_value or existing.raw_value or "")
        if not value or not existing_value:
            continue
        similarity = SequenceMatcher(None, existing_value, value).ratio()
        existing_label = existing.label.strip().lower()
        same_label = existing_label == label
        generic_pair = (
            similarity >= 0.95
            and (
                existing_label in {"identifier", "score", "date"}
                or label in {"identifier", "score", "date"}
            )
        )
        same_category = existing.category == candidate.category and similarity >= 0.9
        if same_label and similarity >= 0.85:
            return index
        if generic_pair or same_category:
            return index
    return None


def _merge_candidates(left: FieldCandidate, right: FieldCandidate) -> FieldCandidate:
    winner = left if left.confidence >= right.confidence else right
    loser = right if winner is left else left
    merged_boxes = list(winner.bounding_boxes)
    for box in loser.bounding_boxes:
        if box not in merged_boxes:
            merged_boxes.append(box)
    merged_detectors = list(dict.fromkeys([*winner.detected_by, *loser.detected_by]))
    merged_frequency = max(winner.signals.frequency, loser.signals.frequency) + 1
    merged = winner.model_copy(
        update={
            "bounding_boxes": merged_boxes,
            "detected_by": merged_detectors,
            "signals": winner.signals.model_copy(update={"frequency": merged_frequency}),
        }
    )
    return merged


def _normalize_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
