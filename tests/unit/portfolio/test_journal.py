"""Tests for the trade journal (DB round-trip, P&L, idempotency)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from momentum.core.enums import RiskVerdict, Side
from momentum.execution.order import Fill
from momentum.portfolio.journal import TradeJournal
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.types import RiskAssessment

ENTRY_TS = dt.datetime(2026, 1, 5, 15, 30, tzinfo=dt.UTC)
EXIT_TS = dt.datetime(2026, 1, 9, 21, 0, tzinfo=dt.UTC)


def assessment(shares: int = 100, entry: float = 50.0, stop: float = 48.0) -> RiskAssessment:
    return RiskAssessment(
        verdict=RiskVerdict.APPROVE,
        symbol="AAPL",
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


def entry_fill(shares: int = 100, price: float = 50.0, fees: float = 1.0) -> Fill:
    return Fill("AAPL-1", "AAPL", Side.LONG, shares, price, fees, ENTRY_TS)


def exit_fill(shares: int = 100, price: float = 60.0, fees: float = 1.0) -> Fill:
    return Fill("AAPL-2", "AAPL", Side.SHORT, shares, price, fees, EXIT_TS)


def test_open_trade_persists_row(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    trade = journal.open_trade(
        entry_fill=entry_fill(),
        assessment=assessment(),
        run_id="paper-1",
        sector="Technology",
        regime_label="bullish",
        entry_reason="momentum_breakout",
    )
    session.commit()

    assert trade.id is not None
    assert trade.status == "open"
    assert trade.symbol == "AAPL"
    assert trade.quantity == 100
    assert trade.entry_price == pytest.approx(50.0)
    assert trade.initial_stop == pytest.approx(48.0)
    assert trade.initial_risk == pytest.approx(200.0)  # stop_distance(2) * 100
    assert trade.sector == "Technology"
    assert trade.regime_label == "bullish"


def test_open_trade_is_idempotent(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    first = journal.open_trade(entry_fill=entry_fill(), assessment=assessment(), run_id="paper-1")
    session.commit()
    second = journal.open_trade(entry_fill=entry_fill(), assessment=assessment(), run_id="paper-1")
    session.commit()

    assert first.id == second.id
    assert TradeRepository(session).count() == 1


def test_open_trade_idempotent_with_lowercase_symbol(session: Session) -> None:
    """A non-uppercase fill symbol must still match on re-run (no duplicate open).

    The lookup uppercases its query key; storing the symbol un-normalized would
    make the second open miss the first row and journal a duplicate.
    """
    journal = TradeJournal(TradeRepository(session))
    fill = Fill("aapl-1", "aapl", Side.LONG, 100, 50.0, 1.0, ENTRY_TS)
    first = journal.open_trade(entry_fill=fill, assessment=assessment(), run_id="paper-1")
    session.commit()
    second = journal.open_trade(entry_fill=fill, assessment=assessment(), run_id="paper-1")
    session.commit()

    assert first.symbol == "AAPL"  # normalized on write
    assert first.id == second.id
    assert TradeRepository(session).count() == 1


def test_close_trade_computes_pnl_and_r(session: Session) -> None:
    repo = TradeRepository(session)
    journal = TradeJournal(repo)
    trade = journal.open_trade(entry_fill=entry_fill(), assessment=assessment(), run_id="paper-1")
    session.commit()

    closed = journal.close_trade(trade, exit_fill(), exit_reason="target")
    session.commit()

    assert closed.status == "closed"
    assert closed.exit_price == pytest.approx(60.0)
    # gross = (60-50)*100 = 1000; fees = 1 (entry) + 1 (exit) = 2; net = 998.
    assert closed.gross_pnl == pytest.approx(1000.0)
    assert closed.fees == pytest.approx(2.0)
    assert closed.net_pnl == pytest.approx(998.0)
    # R = net / initial_risk = 998 / 200.
    assert closed.r_multiple == pytest.approx(4.99)
    assert closed.return_pct == pytest.approx(998.0 / 5000.0)
    assert closed.holding_days == 4
    assert repo.closed("paper-1") == [closed]


def test_close_rejects_quantity_mismatch(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    trade = journal.open_trade(entry_fill=entry_fill(100), assessment=assessment(100))
    session.commit()
    with pytest.raises(ValueError, match="does not match open quantity"):
        journal.close_trade(trade, exit_fill(shares=50), exit_reason="target")


def test_scale_out_banks_partial_pnl(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    trade = journal.open_trade(entry_fill=entry_fill(), assessment=assessment(), run_id="paper-1")
    session.commit()

    journal.scale_out(trade, exit_fill(shares=50, price=58.0, fees=0.5))
    session.commit()

    assert trade.status == "open"
    assert trade.quantity == 50
    assert trade.scaled_out_quantity == 50
    # (58-50)*50 - 0.5 fees = 399.5, net of the scale-out fill's own fees.
    assert trade.scaled_out_pnl == pytest.approx(399.5)
    assert trade.fees == pytest.approx(1.0)  # entry fees only

    closed = journal.close_trade(trade, exit_fill(shares=50, price=60.0), exit_reason="target")
    session.commit()
    # gross = (60-50)*50 + banked 399.5 = 899.5; fees = 1 entry + 1 exit = 2.
    assert closed.gross_pnl == pytest.approx(899.5)
    assert closed.net_pnl == pytest.approx(897.5)
    # Return on the ORIGINAL notional (100 shares * 50).
    assert closed.return_pct == pytest.approx(897.5 / 5000.0)
    assert closed.r_multiple == pytest.approx(897.5 / 200.0)


def test_scale_out_rejects_full_close(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    trade = journal.open_trade(entry_fill=entry_fill(), assessment=assessment())
    session.commit()
    with pytest.raises(ValueError, match="use close_trade"):
        journal.scale_out(trade, exit_fill(shares=100))


def test_update_stop_persists(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    trade = journal.open_trade(entry_fill=entry_fill(), assessment=assessment())
    session.commit()
    journal.update_stop(trade, 52.5)
    session.commit()
    assert trade.current_stop == pytest.approx(52.5)
    assert trade.initial_stop == pytest.approx(48.0)  # never rewritten


def test_close_is_idempotent(session: Session) -> None:
    journal = TradeJournal(TradeRepository(session))
    trade = journal.open_trade(entry_fill=entry_fill(), assessment=assessment())
    session.commit()
    journal.close_trade(trade, exit_fill(), exit_reason="target")
    again = journal.close_trade(trade, exit_fill(price=999.0), exit_reason="manual")
    # Already closed: the second call is a no-op, original numbers preserved.
    assert again.exit_price == pytest.approx(60.0)
    assert again.exit_reason == "target"
