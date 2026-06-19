"""Tests for crash recovery: rebuilding the portfolio from the trade ledger."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from momentum.core.enums import RiskVerdict, Side
from momentum.execution.order import Fill
from momentum.orchestration.recovery import reconstruct_portfolio
from momentum.portfolio.journal import TradeJournal
from momentum.portfolio.portfolio import Portfolio
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.types import RiskAssessment

TS = dt.datetime(2026, 1, 5, 16, 0, tzinfo=dt.UTC)


def _assessment(symbol: str, shares: int, entry: float, stop: float) -> RiskAssessment:
    return RiskAssessment(
        verdict=RiskVerdict.APPROVE,
        symbol=symbol,
        method="atr",
        equity=100_000.0,
        requested_shares=shares,
        approved_shares=shares,
        entry_ref=entry,
        initial_stop=stop,
        stop_distance=entry - stop,
        risk_dollars=(entry - stop) * shares,
        risk_per_trade_pct=0.005,
        base_risk_per_trade_pct=0.005,
        atr=1.0,
    )


def _open(journal: TradeJournal, symbol: str, shares: int, entry: float, stop: float) -> None:
    fill = Fill(f"{symbol}-1", symbol, Side.LONG, shares, entry, 1.0, TS)
    journal.open_trade(
        entry_fill=fill, assessment=_assessment(symbol, shares, entry, stop), run_id="paper-1"
    )


def test_reconstructs_open_positions_and_cash(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    _open(journal, "AAPL", 100, 50.0, 48.0)
    _open(journal, "MSFT", 50, 100.0, 95.0)
    session.commit()

    # Rebuild a fresh portfolio purely from the ledger.
    pf = reconstruct_portfolio(
        TradeRepository(session),
        starting_equity=100_000.0,
        marks={"AAPL": 55.0, "MSFT": 100.0},
    )
    assert set(pf.positions) == {"AAPL", "MSFT"}
    # Cash = 100_000 - (100*50 + 1) - (50*100 + 1) = 89_998.
    assert pf.cash == pytest.approx(89_998.0)
    # Equity = cash + 100*55 + 50*100 = 89_998 + 5_500 + 5_000 = 100_498.
    assert pf.equity == pytest.approx(100_498.0)
    aapl = pf.positions["AAPL"]
    assert aapl.quantity == 100
    assert aapl.stop == pytest.approx(48.0)
    assert aapl.last_price == pytest.approx(55.0)


def test_recovery_matches_live_portfolio(session: Session) -> None:
    # A live portfolio that opened the same trade should equal the recovered one.
    journal = TradeJournal(TradeRepository(session))
    live = Portfolio(cash=100_000.0)
    fill = Fill("AAPL-1", "AAPL", Side.LONG, 100, 50.0, 1.0, TS)
    live.on_fill(fill)
    live.set_stop("AAPL", 48.0)
    live.mark_to_market({"AAPL": 55.0})
    journal.open_trade(
        entry_fill=fill, assessment=_assessment("AAPL", 100, 50.0, 48.0), run_id="paper-1"
    )
    session.commit()

    recovered = reconstruct_portfolio(
        TradeRepository(session), starting_equity=100_000.0, marks={"AAPL": 55.0}
    )
    assert recovered.cash == pytest.approx(live.cash)
    assert recovered.equity == pytest.approx(live.equity)


def test_closed_trades_contribute_realized_pnl(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    _open(journal, "AAPL", 100, 50.0, 48.0)
    session.commit()
    trade = TradeRepository(session).open_for_symbol("AAPL", "paper-1")
    assert trade is not None
    exit_fill = Fill("AAPL-2", "AAPL", Side.SHORT, 100, 60.0, 1.0, TS)
    journal.close_trade(trade, exit_fill, exit_reason="target")
    session.commit()

    pf = reconstruct_portfolio(TradeRepository(session), starting_equity=100_000.0, marks={})
    assert pf.positions == {}
    # net P&L = (60-50)*100 - 2 = 998 -> equity = 100_998.
    assert pf.equity == pytest.approx(100_998.0)


def test_empty_ledger_returns_starting_equity(session: Session) -> None:
    pf = reconstruct_portfolio(TradeRepository(session), starting_equity=50_000.0, marks={})
    assert pf.equity == pytest.approx(50_000.0)
    assert pf.positions == {}
