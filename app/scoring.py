from __future__ import annotations


def priority_score(winrate: float, pickrate: float, banrate: float) -> float:
    """Compute champion priority score from normalized metrics (0..1)."""
    return 0.5 * banrate + 0.3 * pickrate + 0.2 * winrate
