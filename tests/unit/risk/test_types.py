"""Tests for the risk-engine value objects."""

from __future__ import annotations

import pytest

from momentum.core.enums import RegimeState, Side
from momentum.risk.types import AccountState, OpenPosition


def test_open_position_long_metrics() -> None:
    p = OpenPosition("AAA", shares=100, entry_price=50, current_price=55, current_stop=48)
    assert p.market_value == pytest.approx(5500)
    assert p.signed_market_value == pytest.approx(5500)
    assert p.stop_distance == pytest.approx(7.0)  # 55 - 48
    assert p.open_risk == pytest.approx(700.0)


def test_open_position_short_metrics() -> None:
    p = OpenPosition(
        "AAA", shares=100, entry_price=50, current_price=45, current_stop=52, side=Side.SHORT
    )
    assert p.signed_market_value == pytest.approx(-4500)
    assert p.stop_distance == pytest.approx(7.0)  # 52 - 45 (adverse = up)
    assert p.open_risk == pytest.approx(700.0)


def test_open_risk_clamped_when_stop_in_profit() -> None:
    # stop moved above price (locked-in profit) -> no open risk
    p = OpenPosition("AAA", shares=100, entry_price=50, current_price=60, current_stop=62)
    assert p.open_risk == 0.0


def test_account_exposure_and_heat() -> None:
    longs = OpenPosition("L", 100, 50, 50, 45)  # 5000 mv, 500 risk
    shorts = OpenPosition("S", 100, 40, 40, 44, side=Side.SHORT)  # 4000 mv, 400 risk
    acct = AccountState(equity=100_000, open_positions=(longs, shorts))
    assert acct.gross_exposure == pytest.approx(0.09)  # (5000+4000)/100k
    assert acct.net_exposure == pytest.approx(0.01)  # (5000-4000)/100k
    assert acct.total_open_risk == pytest.approx(900.0)
    assert acct.portfolio_heat == pytest.approx(0.009)
    assert acct.num_positions == 2


def test_account_drawdown_and_daily_pnl() -> None:
    acct = AccountState(equity=80_000, peak_equity=100_000, day_start_equity=85_000)
    assert acct.drawdown == pytest.approx(0.20)
    assert acct.daily_pnl_pct == pytest.approx(80_000 / 85_000 - 1)


def test_account_defaults_no_drawdown() -> None:
    acct = AccountState(equity=100_000)
    assert acct.drawdown == 0.0
    assert acct.daily_pnl_pct == 0.0


def test_sector_helpers() -> None:
    a = OpenPosition("A", 100, 50, 50, 45, sector="Tech")
    b = OpenPosition("B", 100, 50, 50, 45, sector="Tech")
    c = OpenPosition("C", 100, 50, 50, 45, sector="Energy")
    acct = AccountState(equity=100_000, open_positions=(a, b, c), regime=RegimeState.BULLISH)
    assert acct.sector_notional("Tech") == pytest.approx(10_000)
    assert acct.positions_in_sector("Tech") == 2
    assert acct.positions_in_sector("Energy") == 1
