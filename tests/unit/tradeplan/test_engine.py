"""Tests for the pure trade-plan engine."""

from __future__ import annotations

import pytest

from momentum.strategy import StrategyConfig
from momentum.tradeplan import TradePlanConfig, TradePlanEngine, TradePlanInputs

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
    equity=100_000.0,
    exit_level=104.0,
    market_uptrend=True,
)


def _engine(**plan_overrides) -> TradePlanEngine:
    """An engine on explicit in-code defaults (no config files involved)."""
    return TradePlanEngine(TradePlanConfig(**plan_overrides), StrategyConfig())


def test_plan_has_all_required_fields():
    plan = _engine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    assert plan.entry == 120.0
    assert plan.stop < plan.entry
    assert plan.risk_per_share > 0
    assert len(plan.targets) == 3
    # milestones strictly increasing in price and R
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
    assert _engine().plan(TradePlanInputs(symbol="X", price=None, atr=4.0)) is None
    assert _engine().plan(TradePlanInputs(symbol="X", price=10.0, atr=None)) is None


def test_stop_is_the_strategys_atr_multiple():
    """The plan's stop is the backtested rule: entry − stop_atr_mult × ATR."""
    strategy = StrategyConfig()
    plan = _engine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    assert plan.stop == pytest.approx(120.0 - strategy.stop_atr_mult * 4.0)  # 108.0
    # Nearby support / EMAs do not move it unless the user opts in.
    near = _engine().plan(TradePlanInputs(**{**BASE, "support_level": 118.0, "ema_fast": 119.0}))
    assert near is not None and near.stop == plan.stop
    assert near.structural_support is None


def test_explicit_stop_multiple_overrides_the_strategy():
    plan = _engine(stop_atr_mult=2.0).plan(TradePlanInputs(**BASE))
    assert plan is not None and plan.stop == pytest.approx(120.0 - 2.0 * 4.0)


def test_structural_stop_is_opt_in():
    # A swing low at 100 sits further than the 3×ATR stop (108): with the option
    # on, the stop snaps just below the pivot.
    plan = _engine(use_structural_stop=True).plan(
        TradePlanInputs(**{**BASE, "support_level": 100.0})
    )
    assert plan is not None
    assert plan.stop == pytest.approx(100.0 * (1.0 - 0.005))
    assert plan.structural_support == 100.0


def test_size_is_fixed_fraction_risk_capped_by_position_limit():
    strategy = StrategyConfig()
    plan = _engine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    # risk 0.5% of 100k = $500 over a $12 stop → 41 shares ($4,920 < the 8% cap)
    assert plan.suggested_shares == 41
    assert plan.suggested_risk_dollars <= strategy.risk_per_trade_pct * 100_000.0
    assert plan.suggested_position_value <= strategy.max_position_pct * 100_000.0
    # A quiet stock (tiny ATR) would size huge by risk alone — the cap binds.
    quiet = _engine().plan(TradePlanInputs(**{**BASE, "atr": 0.2}))
    assert quiet is not None
    assert quiet.suggested_position_value <= strategy.max_position_pct * 100_000.0
    assert quiet.suggested_shares == int(strategy.max_position_pct * 100_000.0 // 120.0)


def test_size_scales_with_account_equity():
    small = _engine().plan(TradePlanInputs(**{**BASE, "equity": 10_000.0}))
    large = _engine().plan(TradePlanInputs(**{**BASE, "equity": 100_000.0}))
    assert small is not None and large is not None
    assert small.suggested_shares < large.suggested_shares
    assert small.suggested_risk_dollars <= 0.005 * 10_000.0


def test_regime_label_does_not_throttle_size():
    """The market gate is on/off (it blocks entries); size is not scaled by label."""
    bull = _engine().plan(TradePlanInputs(**BASE))
    bear = _engine().plan(TradePlanInputs(**{**BASE, "regime": "bear"}))
    assert bull is not None and bear is not None
    assert bear.suggested_shares == bull.suggested_shares


def test_milestones_are_not_sell_orders_and_the_exit_is_the_trend_break():
    plan = _engine().plan(TradePlanInputs(**BASE))
    assert plan is not None
    assert [t.r_multiple for t in plan.targets] == [2.0, 4.0, 8.0]
    assert plan.exit_level == 104.0
    assert "104.00" in plan.exit_rule and "50-day low" in plan.exit_rule
    assert any("no profit target" in line.lower() for line in plan.reward_summary)
    assert any("104.00" in cond for cond in plan.failure_conditions)
    assert plan.to_dict()["exit_level"] == 104.0


def test_downtrend_is_named_in_the_plan():
    plan = _engine().plan(TradePlanInputs(**{**BASE, "market_uptrend": False}))
    assert plan is not None
    assert any("downtrend" in cond.lower() for cond in plan.failure_conditions)


def test_explicit_risk_budget_still_overrides():
    plan = _engine().plan(TradePlanInputs(**{**BASE, "risk_dollars": 240.0}))
    assert plan is not None
    assert plan.suggested_shares == 20  # $240 / $12 a share
