"""Performance rules that need no database."""
from __future__ import annotations

from collections import Counter


def validate_levels(levels: list[tuple[int, str]]) -> str | None:
    """A rating scale has 2 to 10 levels with distinct whole-number values and non-empty labels. Returns an error message or None."""
    if not 2 <= len(levels) <= 10:
        return "A rating scale needs between 2 and 10 levels"
    values = [v for v, _ in levels]
    if len(set(values)) != len(values):
        return "Each level needs its own number"
    if any(v < 1 or v > 100 for v in values):
        return "Level numbers must be between 1 and 100"
    if any(not label.strip() for _, label in levels):
        return "Every level needs a label"
    return None


def kpi_progress(current: float | None, target: float | None) -> int:
    """0-100 progress of a measurable goal (higher is better). No target, or a zero target, means 0."""
    if current is None or not target or target <= 0:
        return 0
    return max(0, min(100, round(100 * current / target)))


def total_weight(weights: list[int]) -> int:
    return sum(weights)


def weights_fit(existing: list[int], new: int, limit: int = 100) -> bool:
    return sum(existing) + new <= limit


def weighted_score(items: list[tuple[int, int]]) -> float | None:
    """[(weight, rating)] -> weighted average rating rounded to 2 decimals; goals with weight 0 count equally when all weights are 0."""
    rated = [(w, r) for w, r in items if r is not None]
    if not rated:
        return None
    total = sum(w for w, _ in rated)
    if total == 0:
        return round(sum(r for _, r in rated) / len(rated), 2)
    return round(sum(w * r for w, r in rated) / total, 2)


def distribution(ratings: list[int], values: list[int]) -> dict[int, int]:
    """How many people got each rating on the scale (every level is present, even with 0)."""
    c = Counter(ratings)
    return {v: c.get(v, 0) for v in values}


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None
