"""Tests for Home-Run rarity calibration & verification.

The headline requirement — Home Runs are < 5% of all signals — is asserted here
against a large, seeded, representative population of signals.
"""

from __future__ import annotations

import random

from momentum.opportunity import (
    HomeRunOpportunityEngine,
    OpportunityConfig,
    OpportunityInputs,
    OpportunityTier,
    calibrate_home_run_min_score,
    home_run_rate,
    tier_distribution,
    verify_rarity,
)
from momentum.opportunity.config import OpportunityTiers


def _population(n: int = 4000, seed: int = 7) -> list[OpportunityInputs]:
    """A representative signal population: a small premium cohort + ordinary noise."""
    rng = random.Random(seed)
    out: list[OpportunityInputs] = []
    for _ in range(n):
        if rng.random() < 0.025:  # ~2.5% genuinely premium setups
            out.append(
                OpportunityInputs(
                    market_regime="bull",
                    new_ath=True,
                    distance_to_ath=0.0,
                    relative_volume=rng.uniform(2.5, 4.0),
                    sector_leadership=rng.uniform(0.9, 1.0),
                    momentum_score=rng.uniform(0.88, 1.0),
                    historical_expectancy_r=rng.uniform(1.0, 1.5),
                    historical_sample_size=rng.randint(20, 40),
                )
            )
        else:  # ordinary signals
            new_ath = rng.random() < 0.18
            rvol = rng.uniform(2.0, 4.0) if rng.random() < 0.12 else max(0.3, rng.gauss(1.2, 0.4))
            out.append(
                OpportunityInputs(
                    market_regime=rng.choices(
                        ["bull", "neutral", "bear"], weights=[0.45, 0.35, 0.20]
                    )[0],
                    new_ath=new_ath,
                    distance_to_ath=0.0 if new_ath else rng.random() * 0.30,
                    relative_volume=rvol,
                    sector_leadership=rng.random(),
                    momentum_score=rng.random(),
                    historical_expectancy_r=rng.gauss(0.2, 0.5),
                    historical_sample_size=rng.randint(0, 40),
                )
            )
    return out


def test_home_runs_are_rare_under_default_config() -> None:
    engine = HomeRunOpportunityEngine()
    pop = _population()
    results = [engine.classify(i) for i in pop]

    rate = home_run_rate(results)
    # The core requirement: Home Runs are < 5% of all signals ...
    assert rate < 0.05
    # ... but the tier is reachable (not a vacuous classifier).
    assert rate > 0.0

    dist = tier_distribution(results)
    assert dist[OpportunityTier.NORMAL] > dist[OpportunityTier.ENHANCED]
    assert dist[OpportunityTier.ENHANCED] > dist[OpportunityTier.HOME_RUN]


def test_verify_rarity_report() -> None:
    engine = HomeRunOpportunityEngine()
    results = [engine.classify(i) for i in _population()]
    report = verify_rarity(results, target_home_run_rate=0.05)
    assert report.ok
    assert report.total == len(results)
    assert report.normal + report.enhanced + report.home_run == report.total
    assert report.home_run_rate < 0.05
    assert report.to_dict()["ok"] is True


def test_calibration_tightens_an_over_loose_config() -> None:
    pop = _population()
    # A deliberately loose config: low score bar and no real gates -> far too many.
    loose = OpportunityConfig(
        tiers=OpportunityTiers(
            enhanced_min_score=40.0,
            home_run_min_score=50.0,
            home_run_require_new_ath=False,
            home_run_min_regime_score=0.0,
            home_run_min_relative_volume=0.01,
            home_run_min_momentum=0.0,
        )
    )
    loose_rate = home_run_rate([HomeRunOpportunityEngine(loose).classify(i) for i in pop])
    assert loose_rate > 0.05  # the problem calibration must fix

    tuned = calibrate_home_run_min_score(pop, config=loose, target_home_run_rate=0.03)
    tuned_rate = home_run_rate([HomeRunOpportunityEngine(tuned).classify(i) for i in pop])
    assert tuned_rate < 0.05
    assert tuned.tiers.home_run_min_score > loose.tiers.home_run_min_score


def test_calibration_on_empty_sample_returns_config() -> None:
    cfg = OpportunityConfig()
    assert calibrate_home_run_min_score([], config=cfg) is cfg
