"""Tests for the conviction scoring engine (pure, no DB)."""
from __future__ import annotations

import math

import pytest

from momentum.conviction import ConvictionBand, ConvictionConfig, ConvictionEngine, ConvictionInputs
from momentum.conviction.config import ConvictionBands, ConvictionWeights


def _perfect() -> ConvictionInputs:
    return ConvictionInputs(
        market_regime="bull", sector_strength=1.0, relative_volume=3.0, distance_to_ath=0.0,
        trend_strength=40.0, breadth=0.70, momentum_score=1.0,
        historical_expectancy_r=1.0, historical_sample_size=20,
    )


def _worst() -> ConvictionInputs:
    return ConvictionInputs(
        market_regime="bear", sector_strength=0.0, relative_volume=1.0, distance_to_ath=0.20,
        trend_strength=15.0, breadth=0.30, momentum_score=0.0,
        historical_expectancy_r=-0.5, historical_sample_size=20,
    )


def test_perfect_inputs_score_100_extreme():
    r = ConvictionEngine().score(_perfect())
    assert r.score == 100.0 and r.band is ConvictionBand.EXTREME


def test_worst_inputs_score_0_low():
    r = ConvictionEngine().score(_worst())
    assert r.score == 0.0 and r.band is ConvictionBand.LOW


def test_missing_inputs_are_neutral_medium():
    r = ConvictionEngine().score(ConvictionInputs())
    assert r.score == 50.0 and r.band is ConvictionBand.MEDIUM


def test_contributions_sum_to_score():
    r = ConvictionEngine().score(_perfect())
    assert len(r.components) == 8
    assert math.isclose(sum(c.contribution for c in r.components), r.score, abs_tol=0.01)


@pytest.mark.parametrize(
    "score,band",
    [(0, "low"), (39.9, "low"), (40, "medium"), (69.9, "medium"),
     (70, "high"), (84.9, "high"), (85, "extreme"), (100, "extreme")],
)
def test_band_boundaries(score, band):
    assert ConvictionBand.from_score(score, ConvictionBands()).value == band


def test_regime_ordering_bull_gt_neutral_gt_bear():
    eng = ConvictionEngine()

    def s(regime: str) -> float:
        return eng.score(ConvictionInputs(market_regime=regime)).score

    assert s("bull") > s("neutral") > s("bear")


def test_relative_volume_is_clamped():
    norm = ConvictionEngine().score(ConvictionInputs(relative_volume=99.0)).normalized_map()
    assert norm["relative_volume"] == 1.0


def test_momentum_is_monotonic():
    eng = ConvictionEngine()
    lo = eng.score(ConvictionInputs(momentum_score=0.0)).score
    hi = eng.score(ConvictionInputs(momentum_score=1.0)).score
    assert hi > lo


def test_historical_small_sample_shrinks_toward_neutral():
    eng = ConvictionEngine()
    thin = eng.score(ConvictionInputs(historical_expectancy_r=1.0, historical_sample_size=2))
    full = eng.score(ConvictionInputs(historical_expectancy_r=1.0, historical_sample_size=20))
    th = thin.normalized_map()["historical_similar_setups"]
    fu = full.normalized_map()["historical_similar_setups"]
    assert 0.5 < th < fu == 1.0


def test_zero_weight_removes_component_influence():
    eng = ConvictionEngine(ConvictionConfig(weights=ConvictionWeights(market_regime=0.0)))
    bull = eng.score(ConvictionInputs(market_regime="bull")).score
    bear = eng.score(ConvictionInputs(market_regime="bear")).score
    assert bull == bear


def test_result_to_dict():
    d = ConvictionEngine().score(_perfect()).to_dict()
    assert d["band"] == "extreme" and d["score"] == 100.0 and len(d["components"]) == 8
