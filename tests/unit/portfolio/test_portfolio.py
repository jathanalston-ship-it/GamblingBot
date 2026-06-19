"""Tests for the Portfolio ledger and the risk-engine bridge."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.core.enums import RegimeState, Side
from momentum.execution.order import Fill
from momentum.portfolio.portfolio import Portfolio
from momentum.risk.risk_manager import RiskManager
from momentum.risk.types import TradeProposal

TS = dt.datetime(2026, 1, 5, 15, 30, tzinfo=dt.UTC)


def fill(symbol: str, side: Side, shares: int, price: float, fees: float = 1.0) -> Fill:
    return Fill("o", symbol, side, shares, price, fees, TS)


def test_buy_reduces_cash_and_holds_value() -> None:
    pf = Portfolio(cash=100_000.0)
    pf.on_fill(fill("AAPL", Side.LONG, 100, 50.0, fees=1.0))
    # Cash out = 100*50 + 1 fee = 5001.
    assert pf.cash == pytest.approx(94_999.0)
    # Marked at fill price, equity ~ starting minus fees.
    assert pf.equity == pytest.approx(99_999.0)


def test_mark_to_market_moves_equity() -> None:
    pf = Portfolio(cash=100_000.0)
    pf.on_fill(fill("AAPL", Side.LONG, 100, 50.0, fees=0.0))
    pf.mark_to_market({"AAPL": 60.0})
    # +10 * 100 = 1000 unrealized over the flat-fee baseline.
    assert pf.equity == pytest.approx(101_000.0)
    assert pf.unrealized_pnl == pytest.approx(1000.0)
    assert pf.peak_equity == pytest.approx(101_000.0)


def test_round_trip_realizes_pnl_and_frees_position() -> None:
    pf = Portfolio(cash=100_000.0)
    pf.on_fill(fill("AAPL", Side.LONG, 100, 50.0, fees=1.0))
    pf.on_fill(fill("AAPL", Side.SHORT, 100, 60.0, fees=1.0))
    assert pf.open_positions == []
    assert len(pf.closed_positions) == 1
    # Net P&L = 1000 gross - 2 fees = 998 -> cash back to 100_998.
    assert pf.cash == pytest.approx(100_998.0)
    assert pf.equity == pytest.approx(100_998.0)
    assert pf.realized_pnl == pytest.approx(998.0)


def test_to_account_state_matches_risk_view() -> None:
    pf = Portfolio(cash=100_000.0)
    pf.on_fill(fill("AAPL", Side.LONG, 100, 50.0, fees=0.0))
    pf.set_stop("AAPL", 45.0)
    pf.mark_to_market({"AAPL": 50.0})
    account = pf.to_account_state(regime=RegimeState.BULLISH)
    assert account.num_positions == 1
    assert account.equity == pytest.approx(pf.equity)
    assert account.regime is RegimeState.BULLISH
    # open risk = (50 - 45) * 100 = 500; heat = 500 / equity.
    assert account.total_open_risk == pytest.approx(500.0)
    assert account.portfolio_heat == pytest.approx(500.0 / pf.equity)


def test_account_state_drives_sizing() -> None:
    # A live portfolio state can be fed straight into the risk gateway.
    pf = Portfolio(cash=100_000.0)
    account = pf.to_account_state()
    proposal = TradeProposal(symbol="NVDA", entry_ref=100.0, atr=2.0, side=Side.LONG)
    assessment = RiskManager().evaluate(proposal, account)
    assert assessment.equity == pytest.approx(100_000.0)
    assert assessment.approved_shares > 0


def test_rejects_negative_starting_cash() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Portfolio(cash=-1.0)


def test_set_stop_unknown_symbol_raises() -> None:
    pf = Portfolio(cash=10_000.0)
    with pytest.raises(KeyError, match="no open position"):
        pf.set_stop("AAPL", 10.0)
