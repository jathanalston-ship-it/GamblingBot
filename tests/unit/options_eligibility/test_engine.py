"""Tests for the pure options-eligibility engine."""

from __future__ import annotations

from momentum.options_eligibility import (
    EligibilityInputs,
    FactorStatus,
    OptionsEligibilityEngine,
    Recommendation,
)


def _assess(**kw: object):
    return OptionsEligibilityEngine().assess(EligibilityInputs(symbol="X", **kw))  # type: ignore[arg-type]


def test_leverage_eligible_for_a_strong_liquid_volatile_setup():
    r = _assess(price=120.0, atr_pct=0.03, dollar_volume=8e7, horizon_days=20, regime="bull")
    assert r.eligible is True
    assert r.recommendation is Recommendation.LEVERAGE
    assert r.confidence >= 55
    assert len(r.factors) == 6


def test_low_liquidity_is_a_hard_fail():
    r = _assess(price=8.0, atr_pct=0.05, dollar_volume=2e6, horizon_days=10, regime="bull")
    assert r.eligible is False
    assert r.recommendation is Recommendation.SHARES
    liq = next(f for f in r.factors if f.name == "liquidity")
    assert liq.status is FactorStatus.FAIL


def test_too_quiet_is_a_hard_fail():
    r = _assess(price=60.0, atr_pct=0.008, dollar_volume=2e8, horizon_days=30, regime="bull")
    assert r.eligible is False
    vol = next(f for f in r.factors if f.name == "volatility")
    assert vol.status is FactorStatus.FAIL


def test_small_expected_move_is_a_hard_fail():
    # explicit tiny expected move overrides the ATR-derived one
    r = _assess(
        price=100.0,
        atr_pct=0.02,
        dollar_volume=1e8,
        horizon_days=10,
        regime="bull",
        expected_move_pct=0.01,
    )
    assert r.eligible is False
    em = next(f for f in r.factors if f.name == "expected_move")
    assert em.status is FactorStatus.FAIL


def test_expected_move_derived_from_atr_and_horizon():
    r = _assess(price=100.0, atr_pct=0.03, dollar_volume=1e8, horizon_days=16, regime="bull")
    # 0.03 * sqrt(16) = 0.12
    assert r.expected_move_pct is not None
    assert abs(r.expected_move_pct - 0.12) < 1e-6


def test_long_horizon_warns_but_is_not_a_hard_veto():
    r = _assess(price=120.0, atr_pct=0.03, dollar_volume=8e7, horizon_days=200, regime="bull")
    th = next(f for f in r.factors if f.name == "time_horizon")
    assert th.status is FactorStatus.WARN  # long hold favours shares, not a veto


def test_missing_data_does_not_hard_fail():
    # no liquidity / ATR data -> WARN (neutral), never a FAIL
    r = _assess(price=None, atr_pct=None, dollar_volume=None, regime=None)
    statuses = {f.name: f.status for f in r.factors}
    assert statuses["liquidity"] is FactorStatus.WARN
    assert statuses["volatility"] is FactorStatus.WARN
