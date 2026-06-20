"""Tests for the pure trade-plan engine."""

from __future__ import annotations

import pytest

from momentum.tradeplan import TradePlanEngine, TradePlanInputs

BASE = dict(
    symbol="NVDA",
    price=120.0,
    atr=4.0,
    ema_fast=116.0,
    ema_mid=110.0,
    ema_slow=100.0,
    distance_from_ath=-0.01,
    relative_volume=1.8,
    sector="Technology",
    conviction_score=87.0,
    conviction_band="extreme",
    regime="bull",
    analog_sample_size=22,
    analog_expectancy_r=0.6,
    analog_win_rate=0.45,
    analog_avg_winner_r=2.4,
    analog_avg_loser_r=-0.9,
    analog_avg_winner_holding_days=18.0,
    analog_avg_mfe_r=4.1,
    risk_pct=0.01,
    risk_dollars=1000.0,
    equity=100_000.0,
)


def test_plan_has_all_required_fields():
    plan = TradePlanEngine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    assert plan.entry == 120.0
    assert plan.stop < plan.entry
    assert plan.risk_per_share > 0
    assert len(plan.targets) == 3
    # targets strictly increasing in price and R
    rs = [t.r_multiple for t in plan.targets]
    prices = [t.price for t in plan.targets]
    assert rs == sorted(rs) and prices == sorted(prices)
    assert plan.final_reward_risk == plan.targets[-1].r_multiple
    assert plan.suggested_shares > 0
    assert plan.expected_holding_days_low < plan.expected_holding_days_high
    # required display sections are populated
    assert plan.risk_summary and plan.reward_summary and plan.failure_conditions
    assert any("stop" in f.lower() for f in plan.failure_conditions)


def test_no_price_or_atr_yields_no_plan():
    assert TradePlanEngine().plan(TradePlanInputs(symbol="X", price=None, atr=4.0)) is None
    assert TradePlanEngine().plan(TradePlanInputs(symbol="X", price=10.0, atr=None)) is None


def test_atr_stop_used_when_wider_than_support():
    # ema_fast (119) is very close to price (120); the 1.8*ATR stop is wider.
    plan = TradePlanEngine().plan(TradePlanInputs(**{**BASE, "ema_fast": 119.0}))
    assert plan is not None
    assert plan.stop == 120.0 - 1.8 * 4.0  # 112.8 (ATR stop wins)


def test_targets_lift_toward_analogs():
    # avg winner 2.4R and MFE 4.1R should lift T2/T3 above the defaults (2.0/3.5).
    plan = TradePlanEngine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    assert plan.targets[1].r_multiple >= 2.4
    assert plan.targets[2].r_multiple >= 4.1


def test_bear_regime_shrinks_size():
    bull = TradePlanEngine().plan(TradePlanInputs(**BASE))
    bear = TradePlanEngine().plan(TradePlanInputs(**{**BASE, "regime": "bear"}))
    assert bull is not None and bear is not None
    assert bear.suggested_shares < bull.suggested_shares


def test_pivot_support_drives_stop():
    # A real swing low at 108 sits further than the 1.8*ATR stop (112.8), so the
    # stop snaps just below the pivot — real structure, not the EMA fallback.
    plan = TradePlanEngine().plan(TradePlanInputs(**{**BASE, "support_level": 108.0}))
    assert plan is not None
    assert plan.stop == pytest.approx(108.0 * (1.0 - 0.005))
    # Without a pivot, the EMA/ATR stop is used instead (wider 1.8*ATR = 112.8).
    base = TradePlanEngine().plan(TradePlanInputs(**BASE))
    assert base is not None and base.stop == pytest.approx(112.8)


def test_resistance_snaps_t1_below_it():
    # Overhead resistance at 124 sits below the default 1R target (127.2) → T1
    # snaps just beneath 124.
    plan = TradePlanEngine().plan(TradePlanInputs(**{**BASE, "resistance_level": 124.0}))
    assert plan is not None
    t1 = plan.targets[0]
    assert t1.price == 124.0 * (1.0 - 0.005)
    assert t1.r_multiple < 1.0  # pulled in below the 1R default
    # ordering preserved
    assert t1.price < plan.targets[1].price < plan.targets[2].price
    assert any("resistance" in s.lower() for s in plan.reward_summary)


def test_size_respects_risk_budget():
    plan = TradePlanEngine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    # shares * risk_per_share ~ risk_dollars (1000 * bull factor 1.0)
    assert plan.suggested_shares * plan.risk_per_share <= 1000.0 + plan.risk_per_share
