"""Shadow-mode tests: generate, never submit; manage; grade; report."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.core.enums import Side
from momentum.shadow import expected_fill, manage_shadow_trade, shadow_report
from momentum.shadow.config import ShadowConfig

NOW = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)


def test_expected_fill_crosses_the_spread_never_midpoint() -> None:
    buy = expected_fill(
        symbol="AAPL", side=Side.LONG, quantity=100, ts=NOW, close=100.0, volume=5e6
    )
    sell = expected_fill(
        symbol="AAPL", side=Side.SHORT, quantity=100, ts=NOW, close=100.0, volume=5e6
    )
    assert buy.price > 100.0  # pays the (estimated) ask + slippage
    assert sell.price < 100.0  # hits the bid − slippage
    assert buy.slippage_bps > 0 and sell.slippage_bps > 0
    assert buy.reference == 100.0


def test_management_stop_target_and_breakeven_ratchet() -> None:
    cfg = ShadowConfig()
    base = {"entry": 100.0, "stop": 95.0, "current_stop": None, "target": 112.0}
    assert manage_shadow_trade(price=94.0, **base, config=cfg).kind == "close_stop"
    assert manage_shadow_trade(price=113.0, **base, config=cfg).kind == "close_target"
    raised = manage_shadow_trade(price=106.0, **base, config=cfg)  # +1.2R
    assert raised.kind == "raise_stop" and raised.new_stop == 100.0
    # After the raise, a fallback to entry closes at the (raised) stop.
    assert (
        manage_shadow_trade(price=99.0, entry=100.0, stop=95.0, current_stop=100.0, target=112.0)
    ).kind == "close_stop"
    assert manage_shadow_trade(price=101.0, **base, config=cfg).kind == "none"


def test_report_grades_the_ledger() -> None:
    trades = [
        {
            "status": "closed",
            "entered_at": "2026-06-01T14:00:00+00:00",
            "last_eval_at": "2026-06-05T14:00:00+00:00",
            "entry_slippage_bps": 4.0,
            "exit_slippage_bps": 5.0,
            "expected_pnl": 900.0,
            "expected_r": 1.8,
            "exit_reason": "target",
        },
        {
            "status": "closed",
            "entered_at": "2026-06-02T14:00:00+00:00",
            "last_eval_at": "2026-06-03T14:00:00+00:00",
            "entry_slippage_bps": 6.0,
            "exit_slippage_bps": 3.0,
            "expected_pnl": -500.0,
            "expected_r": -1.0,
            "exit_reason": "stop",
        },
        {
            "status": "open",
            "entered_at": "2026-06-10T14:00:00+00:00",
            "last_eval_at": "2026-07-01T14:00:00+00:00",
            "entry_slippage_bps": 5.0,
        },
    ]
    report = shadow_report(trades, now=NOW, candidates_seen=9)
    assert report["orders_generated"] == 3
    assert report["orders_submitted"] == 0  # by construction
    assert report["closed"] == 2 and report["open"] == 1
    assert report["pnl"]["expected_total"] == 400.0
    assert report["pnl"]["win_rate"] == 0.5
    assert report["pnl"]["profit_factor"] == 1.8
    assert report["exits"] == {"target": 1, "stop": 1}
    assert report["missed_opportunities"]["left_on_the_table"] == 6
    assert report["execution_accuracy"]["entry_slippage_bps_p50"] == 5.0
    assert report["window_complete"] is False  # nowhere near 60 trading days
    assert report["trading_days_observed"] >= 4


def test_empty_ledger_reports_honestly() -> None:
    report = shadow_report([], now=NOW, candidates_seen=0)
    assert report["orders_generated"] == 0
    assert report["pnl"]["expected_total"] is None
    assert report["pnl"]["win_rate"] is None
    assert report["trading_days_observed"] == 0


def test_window_completion_at_sixty_trading_days() -> None:
    trades = [
        {
            "status": "open",
            "entered_at": f"2026-{3 + i // 28:02d}-{(i % 28) + 1:02d}T14:00:00+00:00",
            "last_eval_at": None,
            "entry_slippage_bps": 5.0,
        }
        for i in range(60)
    ]
    report = shadow_report(trades, now=NOW, candidates_seen=60)
    assert report["trading_days_observed"] >= 60
    assert report["window_complete"] is True


def test_config_is_frozen_and_validated() -> None:
    cfg = ShadowConfig()
    assert cfg.window_trading_days == 60
    with pytest.raises(Exception):  # noqa: B017 — pydantic frozen error type
        cfg.window_trading_days = 10  # type: ignore[misc]
    with pytest.raises(ValueError):
        ShadowConfig(min_conviction_score=200)
