"""Plain-language conviction explanation (pure, reused at write- and read-time).

The conviction breakdown is a structured set of weighted component scores. This
module turns it into signed *impacts* (each factor measured against a neutral
setup) and a one-line narrative. ``run_scan`` calls :func:`explain` to **persist**
the explanation alongside each score; the read API reuses the same logic so a
stored and a recomputed explanation always agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from momentum.conviction.config import ConvictionConfig

# A 50/50 setup — the reference an explainable impact is measured against.
NEUTRAL_NORM: float = ConvictionConfig().normalization.neutral

# Nicer labels for the eight conviction factors.
FACTOR_LABELS: dict[str, str] = {
    "market_regime": "market regime",
    "sector_strength": "sector strength",
    "relative_volume": "relative volume",
    "distance_to_ath": "ATH proximity",
    "trend_strength": "trend quality",
    "breadth": "market breadth",
    "momentum_score": "momentum",
    "historical_similar_setups": "historical analogs",
}


def factor_label(name: str) -> str:
    return FACTOR_LABELS.get(name, name.replace("_", " ").strip())


def _join_phrases(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])} and {items[-1]}"


def contributor_impacts(breakdown: Mapping[str, Any] | None) -> list[tuple[str, str, float]]:
    """``(name, label, impact)`` per factor, ordered by impact (drivers first).

    ``impact`` is how far above/below a neutral setup the factor sat, scaled by its
    share of the total weight — positive lifted the score, negative dragged it.
    """
    components = (breakdown or {}).get("components")
    if not isinstance(components, list):
        return []
    comps = [c for c in components if isinstance(c, dict)]
    total_weight = sum(float(c.get("weight", 0.0) or 0.0) for c in comps) or 1.0
    impacts: list[tuple[str, str, float]] = []
    for c in comps:
        name = str(c.get("name", ""))
        weight = float(c.get("weight", 0.0) or 0.0)
        norm = c.get("normalized")
        normalized = float(norm) if isinstance(norm, int | float) else NEUTRAL_NORM
        impact = (normalized - NEUTRAL_NORM) * weight / total_weight * 100.0
        impacts.append((name, factor_label(name), round(impact, 2)))
    impacts.sort(key=lambda r: r[2], reverse=True)
    return impacts


def explain(
    symbol: str, score: float, band: str, breakdown: Mapping[str, Any] | None
) -> str | None:
    """One-line plain-language explanation of why ``symbol`` scored as it did."""
    impacts = contributor_impacts(breakdown)
    if not impacts:
        return None
    positives = [label for _, label, impact in impacts if impact > 0][:3]
    negatives = [(label, impact) for _, label, impact in impacts if impact < 0]
    if not positives:
        if not negatives:
            return None
        weak = [label for label, _ in sorted(negatives, key=lambda r: r[1])[:2]]
        return (
            f"{symbol} scores {score:.0f}/100 ({band}), weighed down by weak {_join_phrases(weak)}."
        )
    rank = "ranks highly" if score >= 70 else "ranks moderately" if score >= 45 else "ranks low"
    text = f"{symbol} {rank} ({score:.0f}/100) due to strong {_join_phrases(positives)}"
    if negatives:
        worst = min(negatives, key=lambda r: r[1])[0]
        text += f", partly offset by weak {worst}"
    return text + "."
