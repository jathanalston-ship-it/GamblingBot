"""Tests for the Home-Run-opportunity engine (pure, no DB)."""

from __future__ import annotations

import math
from dataclasses import replace

from momentum.opportunity import (
    HomeRunOpportunityEngine,
    OpportunityConfig,
    OpportunityInputs,
    OpportunityTier,
)
from momentum.opportunity.config import OpportunityWeights


def _home_run() -> OpportunityInputs:
    """A setup that clears the score threshold and every Home-Run gate."""
    return OpportunityInputs(
        market_regime="bull",
        new_ath=True,
        distance_to_ath=0.0,
        relative_volume=3.0,
        sector_leadership=1.0,
        momentum_score=1.0,
        historical_expectancy_r=1.5,
        historical_sample_size=25,
    )


def test_perfect_inputs_are_home_run() -> None:
    r = HomeRunOpportunityEngine().classify(_home_run())
    assert r.tier is OpportunityTier.HOME_RUN
    assert r.is_home_run
    assert r.score == 100.0
    assert r.failed_gates == ()
    assert r.reasons  # non-empty explanation


def test_missing_inputs_are_normal() -> None:
    r = HomeRunOpportunityEngine().classify(OpportunityInputs())
    assert r.tier is OpportunityTier.NORMAL
    assert r.score == 50.0  # all six inputs neutral


def test_worst_inputs_are_normal_zero() -> None:
    r = HomeRunOpportunityEngine().classify(
        OpportunityInputs(
            market_regime="bear",
            new_ath=False,
            distance_to_ath=0.20,
            relative_volume=1.0,
            sector_leadership=0.0,
            momentum_score=0.0,
            historical_expectancy_r=-0.5,
            historical_sample_size=25,
        )
    )
    assert r.tier is OpportunityTier.NORMAL
    assert r.score == 0.0


def test_contributions_sum_to_score() -> None:
    r = HomeRunOpportunityEngine().classify(_home_run())
    assert len(r.components) == 6
    assert math.isclose(sum(c.contribution for c in r.components), r.score, abs_tol=0.01)


# --------------------------------------------------------------------------- #
# Each hard gate, broken in isolation, blocks the Home-Run tier (-> Enhanced)
# --------------------------------------------------------------------------- #
def test_no_new_ath_blocks_home_run() -> None:
    # at the prior high (score stays high) but not a fresh breakout
    r = HomeRunOpportunityEngine().classify(
        OpportunityInputs(
            market_regime="bull",
            new_ath=False,
            distance_to_ath=0.0,
            relative_volume=3.0,
            sector_leadership=1.0,
            momentum_score=1.0,
            historical_expectancy_r=1.5,
            historical_sample_size=25,
        )
    )
    assert r.tier is OpportunityTier.ENHANCED
    assert "new_ath" in r.failed_gates


def test_neutral_regime_blocks_home_run() -> None:
    r = HomeRunOpportunityEngine().classify(replace(_home_run(), market_regime="neutral"))
    assert r.tier is OpportunityTier.ENHANCED
    assert "market_regime" in r.failed_gates


def test_thin_volume_blocks_home_run() -> None:
    r = HomeRunOpportunityEngine().classify(replace(_home_run(), relative_volume=1.5))
    assert r.tier is OpportunityTier.ENHANCED
    assert "relative_volume" in r.failed_gates


def test_weak_momentum_blocks_home_run() -> None:
    r = HomeRunOpportunityEngine().classify(replace(_home_run(), momentum_score=0.6))
    assert r.tier is OpportunityTier.ENHANCED
    assert "momentum" in r.failed_gates


def test_missing_volume_and_momentum_fail_gates() -> None:
    # gate inputs absent -> gates fail (unconfirmed never qualifies)
    r = HomeRunOpportunityEngine().classify(OpportunityInputs(market_regime="bull", new_ath=True))
    assert not r.is_home_run
    assert {"relative_volume", "momentum"} <= set(r.failed_gates)


# --------------------------------------------------------------------------- #
# Scoring behaviour
# --------------------------------------------------------------------------- #
def test_new_ath_flag_beats_mere_proximity() -> None:
    eng = HomeRunOpportunityEngine()
    fresh = eng.classify(OpportunityInputs(new_ath=True)).normalized_map()["new_ath"]
    near = eng.classify(OpportunityInputs(new_ath=False, distance_to_ath=0.05)).normalized_map()[
        "new_ath"
    ]
    assert fresh == 1.0 and near < 1.0


def test_relative_volume_is_clamped() -> None:
    norm = (
        HomeRunOpportunityEngine()
        .classify(OpportunityInputs(relative_volume=99.0))
        .normalized_map()
    )
    assert norm["relative_volume"] == 1.0


def test_regime_ordering_bull_gt_neutral_gt_bear() -> None:
    eng = HomeRunOpportunityEngine()

    def s(regime: str) -> float:
        return eng.classify(OpportunityInputs(market_regime=regime)).score

    assert s("bull") > s("neutral") > s("bear")


def test_historical_small_sample_shrinks_toward_neutral() -> None:
    eng = HomeRunOpportunityEngine()
    thin = eng.classify(OpportunityInputs(historical_expectancy_r=1.5, historical_sample_size=2))
    full = eng.classify(OpportunityInputs(historical_expectancy_r=1.5, historical_sample_size=20))
    th = thin.normalized_map()["historical_analogs"]
    fu = full.normalized_map()["historical_analogs"]
    assert 0.5 < th < fu == 1.0


def test_zero_weight_removes_component_influence() -> None:
    eng = HomeRunOpportunityEngine(OpportunityConfig(weights=OpportunityWeights(market_regime=0.0)))
    bull = eng.classify(OpportunityInputs(market_regime="bull")).score
    bear = eng.classify(OpportunityInputs(market_regime="bear")).score
    assert bull == bear


def test_result_to_dict() -> None:
    d = HomeRunOpportunityEngine().classify(_home_run()).to_dict()
    assert d["tier"] == "home_run"
    assert d["score"] == 100.0
    assert d["new_ath"] is True
    assert len(d["components"]) == 6
    assert len(d["gates"]) == 4
    assert d["reasons"]


def test_tier_helpers() -> None:
    assert OpportunityTier.HOME_RUN.is_home_run
    assert not OpportunityTier.ENHANCED.is_home_run
    assert OpportunityTier.HOME_RUN.display == "Home Run"
