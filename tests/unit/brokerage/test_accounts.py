"""Account-math tests: settlement, drawdown, sharpe, metrics."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.brokerage.accounts import (
    PendingSettlement,
    compute_account_metrics,
    max_drawdown,
    settlement_time,
    sharpe_ratio,
    split_settled,
)

FRIDAY = dt.datetime(2026, 7, 3, 18, 0, tzinfo=dt.UTC)


def test_settlement_skips_the_weekend() -> None:
    settles = settlement_time(FRIDAY, 1)
    assert settles.weekday() == 0  # Friday + T+1 business day = Monday
    assert settles.date() == dt.date(2026, 7, 6)


def test_split_settled_releases_matured_holds() -> None:
    now = dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.UTC)
    pending = [
        PendingSettlement(1_000.0, now + dt.timedelta(hours=4)),  # still held
        PendingSettlement(2_000.0, now - dt.timedelta(hours=1)),  # matured
    ]
    settled, unsettled, still = split_settled(10_000.0, pending, now)
    assert unsettled == 1_000.0
    assert settled == 9_000.0
    assert len(still) == 1


def test_max_drawdown() -> None:
    assert max_drawdown([100, 110, 99, 121]) == pytest.approx(0.1)
    assert max_drawdown([100, 101, 102]) == 0.0
    assert max_drawdown([]) == 0.0


def test_sharpe_needs_variance() -> None:
    assert sharpe_ratio([100.0, 100.0, 100.0]) is None  # zero-variance
    up = sharpe_ratio([100, 101, 102.5, 103, 104.5])
    assert up is not None and up > 0


def test_metrics_full_picture() -> None:
    m = compute_account_metrics(
        settled_cash=50_000.0,
        unsettled_cash=5_000.0,
        positions_market_value=48_000.0,
        positions_cost_basis=45_000.0,
        open_risk=2_500.0,
        starting_cash=100_000.0,
        margin_multiplier=2.0,
        day_start_equity=101_000.0,
        equity_history=[100_000.0, 101_000.0],
        closed_r_multiples=[2.0, -1.0, 3.0],
        closed_pnls=[400.0, -200.0, 900.0],
    )
    assert m.equity == pytest.approx(103_000.0)
    assert m.buying_power == pytest.approx(100_000.0)  # settled x margin only
    assert m.used_buying_power == pytest.approx(45_000.0)
    assert m.daily_pnl == pytest.approx(2_000.0)
    assert m.total_pnl == pytest.approx(3_000.0)
    assert m.trade_count == 3
    assert m.win_rate == pytest.approx(2 / 3)
    assert m.expectancy_r == pytest.approx((2 - 1 + 3) / 3)
    assert m.open_risk == 2_500.0


def test_metrics_empty_account() -> None:
    m = compute_account_metrics(
        settled_cash=100_000.0,
        unsettled_cash=0.0,
        positions_market_value=0.0,
        positions_cost_basis=0.0,
        open_risk=0.0,
        starting_cash=100_000.0,
        margin_multiplier=1.0,
        day_start_equity=None,
        equity_history=[],
        closed_r_multiples=[],
        closed_pnls=[],
    )
    assert m.win_rate is None
    assert m.expectancy_r is None
    assert m.daily_pnl == 0.0
    assert m.max_drawdown == 0.0
