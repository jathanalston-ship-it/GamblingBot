"""Tests for the pure conviction narrative/explanation generator."""

from __future__ import annotations

from momentum.conviction import narrative
from momentum.conviction.engine import ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs


def _strong_breakdown() -> dict[str, object]:
    inputs = ConvictionInputs(
        market_regime="bullish",
        sector_strength=0.95,
        relative_volume=3.0,
        distance_to_ath=0.01,
        breadth=0.8,
        momentum_score=0.95,
    )
    return ConvictionEngine().score(inputs).to_dict()


def test_no_breakdown_yields_no_explanation() -> None:
    assert narrative.explain("AAA", 50.0, "MEDIUM", None) is None
    assert narrative.explain("AAA", 50.0, "MEDIUM", {}) is None
    assert narrative.contributor_impacts(None) == []


def test_strong_setup_explained_as_high() -> None:
    breakdown = _strong_breakdown()
    text = narrative.explain("NVDA", 88.0, "EXTREME", breakdown)
    assert text is not None
    assert text.startswith("NVDA ranks highly (88/100)")
    assert "due to strong" in text


def test_impacts_sorted_drivers_first() -> None:
    impacts = narrative.contributor_impacts(_strong_breakdown())
    assert impacts  # non-empty
    # Ordered by impact descending.
    assert impacts == sorted(impacts, key=lambda r: r[2], reverse=True)
    # Labels are the friendly names, not raw keys.
    assert all("_" not in label for _, label, _ in impacts)


def test_weak_setup_explained_as_dragged_down() -> None:
    inputs = ConvictionInputs(
        market_regime="bearish",
        sector_strength=0.05,
        relative_volume=0.3,
        distance_to_ath=0.5,
        breadth=0.1,
        momentum_score=0.05,
    )
    result = ConvictionEngine().score(inputs)
    text = narrative.explain("XYZ", result.score, result.band.value, result.to_dict())
    assert text is not None
    assert "weighed down by weak" in text
