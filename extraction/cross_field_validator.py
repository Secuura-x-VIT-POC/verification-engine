from __future__ import annotations

from collections import defaultdict

from .models import FieldCandidate, VerificationStatus


def validate_cross_fields(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    updated = [candidate.model_copy(deep=True) for candidate in candidates]
    by_label: dict[str, list[FieldCandidate]] = defaultdict(list)
    for candidate in updated:
        by_label[candidate.label.strip().lower()].append(candidate)

    for siblings in by_label.values():
        normalized_values = {
            (candidate.normalized_value or candidate.raw_value or "").strip().lower()
            for candidate in siblings
            if (candidate.normalized_value or candidate.raw_value)
        }
        if len(normalized_values) == 1 and len(siblings) > 1:
            for candidate in siblings:
                candidate.signals.frequency = max(candidate.signals.frequency, len(siblings))
                candidate.confidence = min(1.0, round(candidate.confidence + 0.05, 4))
        elif len(normalized_values) > 1:
            for candidate in siblings:
                candidate.verification_status = VerificationStatus.AMBER
                candidate.confidence = max(0.0, round(candidate.confidence - 0.12, 4))

    has_institution = any(candidate.category == "institution" for candidate in updated)
    for candidate in updated:
        value = (candidate.normalized_value or candidate.raw_value or "").strip()
        label = candidate.label.lower()
        if candidate.category == "score":
            numeric = _parse_float(value)
            if numeric is not None:
                if "cgpa" in label or "gpa" in label:
                    if numeric < 0 or numeric > 10:
                        _mark_amber(candidate, penalty=0.15)
                elif "%" in value or "percentage" in label:
                    if numeric < 0 or numeric > 100:
                        _mark_amber(candidate, penalty=0.15)
        if candidate.category == "credential_title" and not has_institution:
            _mark_amber(candidate, penalty=0.08)

    return updated


def summarize_credential_validation(candidates: list[FieldCandidate], field_ids: list[str]) -> tuple[list[str], VerificationStatus]:
    notes: list[str] = []
    status = VerificationStatus.GREEN
    scoped = [candidate for candidate in candidates if candidate.field_id in field_ids]
    if not scoped:
        return notes, status

    amber_candidates = [candidate for candidate in scoped if candidate.verification_status == VerificationStatus.AMBER]
    red_candidates = [candidate for candidate in scoped if candidate.verification_status == VerificationStatus.RED]

    if red_candidates:
        status = VerificationStatus.RED
        notes.append("Verifier feedback reported a mismatch for at least one extracted field.")
    elif amber_candidates:
        status = VerificationStatus.AMBER
        notes.append("Cross-field validation found conflicts or incomplete supporting context.")

    if any(candidate.signals.frequency > 1 for candidate in scoped):
        notes.append("Repeated values across the document strengthened confidence for some fields.")
    return notes, status


def _parse_float(value: str) -> float | None:
    try:
        return float(value.replace("%", "").replace("/10", "").strip())
    except ValueError:
        return None


def _mark_amber(candidate: FieldCandidate, *, penalty: float) -> None:
    candidate.verification_status = VerificationStatus.AMBER
    candidate.confidence = max(0.0, round(candidate.confidence - penalty, 4))
