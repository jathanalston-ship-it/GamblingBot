"""Tests for the top-level performance report."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.analytics import OBJECTIVE_METRICS, Trade, analyze_performance


@pytest.fixture
def scenario() -> tuple[pd.Series, list[Trade]]:
    trades = [
        Trade(f"L{i}", pnl=-750, r_multiple=-1.0, holding_days=8, mfe_r=0.5) for i in range(13)
    ]
    wins = [2.0, 3.0, 2.5, 6.0, 4.0, 2.0, 9.0]
    trades += [
        Trade(f"W{i}", pnl=r * 750, r_multiple=r, holding_days=40, mfe_r=r * 1.2)
        for i, r in enumerate(wins)
    ]
    equity = pd.Series(
        100_000 + np.cumsum([t.pnl for t in trades]),
        index=pd.date_range("2022-01-01", periods=len(trades), freq="7D"),
    )
    return equity, trades


def test_objective_is_headline(scenario) -> None:
    equity, trades = scenario
    rep = analyze_performance(equity, trades, periods_per_year=52)
    assert set(rep.objective) == set(OBJECTIVE_METRICS)
    assert rep.objective["expectancy_r"] is not None
    assert rep.objective["expectancy_r"] > 0


def test_equity_metrics_present(scenario) -> None:
    equity, trades = scenario
    rep = analyze_performance(equity, trades, periods_per_year=52)
    assert rep.cagr > 0
    assert rep.max_drawdown <= 0
    assert rep.sortino > 0


def test_to_optimization_record(scenario) -> None:
    equity, trades = scenario
    rep = analyze_performance(equity, trades, periods_per_year=52)
    rec = rep.to_optimization_record()
    assert rec["expectancy_r"] > 0
    assert rec["num_trades"] == 20
    assert rec["win_rate"] == pytest.approx(0.35)
    assert "profit_factor" in rec
    assert rec["max_drawdown"] <= 0


def test_profit_factor_inf_maps_to_none() -> None:
    # all winners -> profit factor inf -> stored as None
    trades = [Trade("W", pnl=1000, r_multiple=2.0) for _ in range(3)]
    equity = pd.Series(
        [100_000, 101_000, 102_000, 103_000], index=pd.date_range("2022-01-01", periods=4, freq="D")
    )
    rep = analyze_performance(equity, trades)
    assert rep.to_optimization_record()["profit_factor"] is None


def test_summary_renders(scenario) -> None:
    equity, trades = scenario
    rep = analyze_performance(equity, trades, periods_per_year=52)
    text = rep.summary()
    assert "expectancy" in text
    assert "win rate (reported)" in text  # reported, not optimised


def test_to_dict_structure(scenario) -> None:
    equity, trades = scenario
    rep = analyze_performance(equity, trades, periods_per_year=52)
    d = rep.to_dict()
    assert set(d) == {"objective", "trades", "equity", "drawdown"}
    assert d["trades"]["num_trades"] == 20
