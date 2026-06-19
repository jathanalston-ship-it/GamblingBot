"""Tests for the Position lifecycle and P&L math."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.core.enums import Side
from momentum.execution.order import Fill
from momentum.portfolio.position import Position

TS = dt.datetime(2026, 1, 5, 15, 30, tzinfo=dt.UTC)


def fill(side: Side, shares: int, price: float, fees: float = 0.0) -> Fill:
    return Fill("o", "AAPL", side, shares, price, fees, TS)


def test_open_long_sets_state() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 100, 50.0, fees=1.0))
    assert pos.is_open
    assert pos.side is Side.LONG
    assert pos.quantity == 100
    assert pos.avg_price == pytest.approx(50.0)
    assert pos.realized_pnl == pytest.approx(-1.0)  # entry fee


def test_add_updates_vwap() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 40, 100.0))
    pos.apply_fill(fill(Side.LONG, 60, 110.0))
    assert pos.quantity == 100
    assert pos.avg_price == pytest.approx(106.0)


def test_unrealized_pnl_tracks_mark() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 100, 50.0))
    pos.mark(55.0)
    assert pos.unrealized_pnl == pytest.approx(500.0)
    assert pos.market_value == pytest.approx(5500.0)
    assert pos.signed_market_value == pytest.approx(5500.0)


def test_full_close_realizes_pnl_and_closes() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 100, 50.0, fees=1.0))
    pos.apply_fill(fill(Side.SHORT, 100, 60.0, fees=1.0))  # sell to close
    assert not pos.is_open
    assert pos.quantity == 0
    # gross = (60-50)*100 = 1000; fees = 2; realized = 998.
    assert pos.realized_pnl == pytest.approx(998.0)
    assert pos.unrealized_pnl == 0.0
    assert pos.closed_ts == TS


def test_partial_close() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 100, 50.0))
    pos.apply_fill(fill(Side.SHORT, 40, 60.0))
    assert pos.is_open
    assert pos.quantity == 60
    assert pos.realized_pnl == pytest.approx(400.0)  # (60-50)*40


def test_cannot_flip_position() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 100, 50.0))
    with pytest.raises(ValueError, match="flip is not supported"):
        pos.apply_fill(fill(Side.SHORT, 150, 60.0))


def test_fill_symbol_must_match() -> None:
    pos = Position("AAPL")
    with pytest.raises(ValueError, match="does not match"):
        pos.apply_fill(Fill("o", "MSFT", Side.LONG, 10, 50.0, 0.0, TS))


def test_r_multiple_requires_stop() -> None:
    pos = Position("AAPL")
    pos.apply_fill(fill(Side.LONG, 100, 50.0))
    assert pos.r_multiple is None  # no stop yet
    pos.set_stop(48.0)  # 1R = 2.0 * 100 = 200
    pos.mark(54.0)  # +4 * 100 = 400 unrealized
    assert pos.initial_risk == pytest.approx(200.0)
    assert pos.r_multiple == pytest.approx(2.0)


def test_to_open_position_bridges_to_risk() -> None:
    pos = Position("AAPL", sector="Tech")
    pos.apply_fill(fill(Side.LONG, 100, 50.0))
    pos.set_stop(48.0)
    pos.mark(52.0)
    op = pos.to_open_position()
    assert op.symbol == "AAPL"
    assert op.shares == 100
    assert op.entry_price == pytest.approx(50.0)
    assert op.current_price == pytest.approx(52.0)
    assert op.current_stop == pytest.approx(48.0)
    assert op.sector == "Tech"
    # open_risk = (52 - 48) * 100 = 400 (distance to stop).
    assert op.open_risk == pytest.approx(400.0)


def test_to_open_position_raises_when_flat() -> None:
    pos = Position("AAPL")
    with pytest.raises(ValueError, match="not open"):
        pos.to_open_position()
