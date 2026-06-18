"""Tests for the philosophy-centric trade analytics."""

from __future__ import annotations

import pytest

from momentum.analytics.trade_analysis import Trade, compute_trade_stats


def _skewed_trades() -> list[Trade]:
    """13 small losers, 7 large winners — sub-50% win rate, positive expectancy."""
    trades = [
        Trade(f"L{i}", pnl=-750, r_multiple=-1.0, holding_days=8, mfe_r=0.5) for i in range(13)
    ]
    wins = [2.0, 3.0, 2.5, 6.0, 4.0, 2.0, 9.0]
    trades += [
        Trade(f"W{i}", pnl=r * 750, r_multiple=r, holding_days=40, mfe_r=r * 1.2)
        for i, r in enumerate(wins)
    ]
    return trades


def test_empty() -> None:
    s = compute_trade_stats([])
    assert s.num_trades == 0
    assert s.expectancy_r == 0.0
    assert s.trend_capture is None


def test_low_win_rate_positive_expectancy() -> None:
    s = compute_trade_stats(_skewed_trades())
    assert s.num_trades == 20
    assert s.win_rate == pytest.approx(0.35)  # sub-50% is fine
    assert s.expectancy_r > 0  # the objective is still positive
    assert s.profit_factor > 1.0


def test_objective_metrics() -> None:
    s = compute_trade_stats(_skewed_trades())
    assert s.avg_winner_r == pytest.approx(sum([2, 3, 2.5, 6, 4, 2, 9]) / 7)
    assert s.largest_winner_r == 9.0
    assert s.largest_loser_r == -1.0
    assert s.payoff_ratio > 1.0  # winners dwarf losers


def test_asymmetry_and_skew() -> None:
    s = compute_trade_stats(_skewed_trades())
    assert s.payoff_ratio > 3.0
    assert s.r_skew > 0  # fat right tail
    assert s.tail_ratio > 1.0
    assert s.top5_winner_profit_share > 0.5  # a few winners carry the system


def test_winners_held_longer() -> None:
    s = compute_trade_stats(_skewed_trades())
    assert s.avg_winner_holding_days > s.avg_loser_holding_days
    assert s.winner_loser_hold_ratio > 1.0  # let winners run, cut losers


def test_trend_capture() -> None:
    # realised R / MFE R across winners; winners realise 1/1.2 of their peak
    s = compute_trade_stats(_skewed_trades())
    assert s.trend_capture == pytest.approx(1 / 1.2, rel=1e-3)


def test_trend_capture_none_without_mfe() -> None:
    trades = [Trade("W", pnl=1000, r_multiple=2.0, holding_days=10)]  # no mfe
    assert compute_trade_stats(trades).trend_capture is None


def test_streaks() -> None:
    # WWW L WW -> max wins 3, max losses 1
    trades = [
        Trade("a", 1, 1.0),
        Trade("b", 1, 1.0),
        Trade("c", 1, 1.0),
        Trade("d", -1, -1.0),
        Trade("e", 1, 1.0),
        Trade("f", 1, 1.0),
    ]
    s = compute_trade_stats(trades)
    assert s.max_consecutive_wins == 3
    assert s.max_consecutive_losses == 1


def test_profit_factor_and_net() -> None:
    s = compute_trade_stats(_skewed_trades())
    # gross profit = 28.5R*750 = 21375; gross loss = 13*750 = 9750
    assert s.gross_profit == pytest.approx(28.5 * 750)
    assert s.gross_loss == pytest.approx(-9750)
    assert s.net_profit == pytest.approx(28.5 * 750 - 9750)
    assert s.profit_factor == pytest.approx(21375 / 9750)


def test_headline_keys() -> None:
    s = compute_trade_stats(_skewed_trades())
    head = s.headline()
    assert set(head) == {
        "expectancy_r",
        "profit_factor",
        "avg_winner_r",
        "largest_winner_r",
        "trend_capture",
        "payoff_ratio",
    }
    assert "win_rate" not in head  # win rate is NOT an objective
