from __future__ import annotations

from .models import ExtractionSignals, FieldCandidate


WEIGHTS = {
    "regex_score": 0.28,
    "layout_score": 0.16,
    "llm_score": 0.14,
    "ner_score": 0.1,
    "ocr_confidence": 0.14,
    "semantic_score": 0.13,
}


def score_candidate(candidate: FieldCandidate) -> FieldCandidate:
    signals = _ensure_non_zero_signal(candidate.signals)
    weighted_sum = sum(float(getattr(signals, key) or 0.0) * weight for key, weight in WEIGHTS.items())
    frequency_boost = min(0.08, 0.02 * max(signals.frequency - 1, 0))
    confidence = round(max(0.0, min(1.0, weighted_sum + frequency_boost + 0.05)), 4)
    return candidate.model_copy(update={"signals": signals, "confidence": confidence})


def compute_extraction_quality(candidates: list[FieldCandidate], grounded_ratio: float, avg_ocr_confidence: float) -> float:
    if not candidates:
        return 0.0
    avg_candidate_confidence = sum(candidate.confidence for candidate in candidates) / len(candidates)
    diversity = len({detector for candidate in candidates for detector in candidate.detected_by}) / 5.0
    score = (
        (avg_candidate_confidence * 0.55)
        + (grounded_ratio * 0.25)
        + (max(avg_ocr_confidence, 0.4) * 0.1)
        + (min(diversity, 1.0) * 0.1)
    )
    return round(max(0.0, min(1.0, score)), 4)


def _ensure_non_zero_signal(signals: ExtractionSignals) -> ExtractionSignals:
    if any(
        float(getattr(signals, key) or 0.0) > 0.0
        for key in ("regex_score", "layout_score", "llm_score", "ner_score", "ocr_confidence", "semantic_score")
    ):
        return signals
    return signals.model_copy(update={"semantic_score": 0.25})
