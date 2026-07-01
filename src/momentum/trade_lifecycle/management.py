"""Management-quality analytics over tracked trades (pure helpers).

These metrics grade the *management logic itself* — not win rate, not profit —
so improvement is visible regardless of market conditions: how conviction and
health behave over a trade's life, how theses age, and which health levels
actually preceded good outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def conviction_decay(original: float | None, latest: float | None) -> float | None:
    """Signed conviction change over the trade's life (negative = decayed)."""
    if original is None or latest is None:
        return None
    return latest - original


def conviction_recovery(convictions: Sequence[float]) -> float | None:
    """How far conviction rebounded after its deepest dip below the start.

    Returns ``None`` when there is no dip (fewer than 3 readings, or conviction
    never fell below its first value) — recoveries only exist after dips.
    """
    if len(convictions) < 3:
        return None
    first = convictions[0]
    low_idx = min(range(len(convictions)), key=lambda i: convictions[i])
    if convictions[low_idx] >= first or low_idx == len(convictions) - 1:
        return None
    rebound = max(convictions[low_idx + 1 :]) - convictions[low_idx]
    return rebound if rebound > 0 else None


def best_health_bucket(
    pairs: Sequence[tuple[float, float]], *, bucket_size: int = 10
) -> dict[str, Any] | None:
    """The health-score decile whose trades realized the best average R.

    ``pairs`` is (average health over the trade's evaluations, realized R).
    """
    if not pairs:
        return None
    buckets: dict[int, list[float]] = {}
    for health, realized_r in pairs:
        key = min(int(health // bucket_size), (100 // bucket_size) - 1)
        buckets.setdefault(key, []).append(realized_r)
    best_key = max(buckets, key=lambda k: sum(buckets[k]) / len(buckets[k]))
    rs = buckets[best_key]
    return {
        "bucket": f"{best_key * bucket_size}-{(best_key + 1) * bucket_size}",
        "avg_realized_r": round(sum(rs) / len(rs), 4),
        "trades": len(rs),
    }
