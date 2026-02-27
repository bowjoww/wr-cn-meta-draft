from __future__ import annotations

from math import sqrt


EPSILON = 0.01


def priority_score(winrate: float, pickrate: float, banrate: float) -> float:
    """Compute champion priority score from normalized metrics (0..1)."""
    return 0.5 * banrate + 0.3 * pickrate + 0.2 * winrate


def power_score(winrate: float, pickrate: float, banrate: float, avg_winrate: float, eps: float = EPSILON) -> float:
    """Compute power score inspired by PBI-like metric."""
    return (winrate - avg_winrate) * sqrt(max(pickrate, 0.0)) / (1 - banrate + eps)


def zscore(value: float, mean: float, std_dev: float) -> float:
    if std_dev <= 0:
        return 0.0
    return (value - mean) / std_dev
