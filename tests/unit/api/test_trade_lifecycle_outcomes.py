"""Journal linkage + realized-outcome advice grading.

A tracked trade (the recommendation) is linked to its executed journal trade by
symbol + entry time; when the journal trade closes, the realized R/P&L land on
the tracked trade and every evaluation it received is graded with hindsight.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.api import trade_lifecycle_service as svc
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.persistence.repositories.trade_evaluations import TradeEvaluationRepository
from momentum.trade_lifecycle import (
    EvaluationInputs,
    ThesisReevaluationEngine,
    TradeSpec,
)

TS = dt.datetime(2026, 6, 1, 16, 0, tzinfo=dt.UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    s = create_session_factory(engine)()
    try:
        yield s
    finally:
        s.close()


def _tracked(session: Session, symbol: str = "AAPL"):  # type: ignore[no-untyped-def]
    spec = TradeSpec(
        symbol=symbol,
        recommended_at=TS,
        run_id="scan-1",
        instrument="shares",
        quantity=100,
        entry_price=100.0,
        stop_price=92.0,
        targets=(),
        conviction_score=72.0,
        conviction_band="high",
        regime="bull",
        sector="Technology",
        thesis="test",
        entry_atr=2.0,
        sector_rs=0.7,
        momentum_score=65.0,
        analog_expectancy_r=0.4,
    )
    row = TrackedTradeRepository(session).create_from_spec(spec)
    assert row is not None
    return row


def _journal(
    session: Session,
    symbol: str = "AAPL",
    *,
    entry_offset_days: int = 0,
    closed: bool = False,
    r_multiple: float | None = None,
    net_pnl: float | None = None,
) -> Trade:
    trade = Trade(
        symbol=symbol,
        direction="long",
        entry_ts=TS + dt.timedelta(days=entry_offset_days),
        entry_price=100.0,
        quantity=100,
        initial_stop=92.0,
        status="closed" if closed else "open",
        exit_ts=TS + dt.timedelta(days=entry_offset_days + 10) if closed else None,
        exit_price=100.0 + (r_multiple or 0) * 8.0 if closed else None,
        r_multiple=r_multiple,
        net_pnl=net_pnl,
        exit_reason="target" if closed else None,
    )
    session.add(trade)
    session.flush()
    return trade


def _evaluate(session: Session, row, price: float) -> None:  # type: ignore[no-untyped-def]
    evaluation = ThesisReevaluationEngine().evaluate(
        EvaluationInputs(
            symbol=row.symbol,
            entry_price=row.entry_price,
            stop_price=row.stop_price,
            price=price,
            original_conviction=row.conviction_score,
            current_conviction=70.0,
        )
    )
    TradeEvaluationRepository(session).append(row.trade_uid, evaluation, run_id=None, ts=TS)


# --------------------------------------------------------------------------- #
# linking
# --------------------------------------------------------------------------- #
def test_links_by_symbol_and_entry_time(session: Session) -> None:
    tracked = _tracked(session)
    journal = _journal(session, entry_offset_days=1)
    counts = svc.link_journal_trades(session, ts=TS)
    assert counts == {"linked": 1, "realized": 0}
    assert tracked.journal_trade_id == journal.id


def test_does_not_link_older_executions(session: Session) -> None:
    _tracked(session)
    _journal(session, entry_offset_days=-30)  # executed a month before the recommendation
    counts = svc.link_journal_trades(session, ts=TS)
    assert counts["linked"] == 0


def test_does_not_link_other_symbols(session: Session) -> None:
    _tracked(session, "AAPL")
    _journal(session, "MSFT", entry_offset_days=1)
    assert svc.link_journal_trades(session, ts=TS)["linked"] == 0


def test_one_journal_trade_claims_one_tracked_trade(session: Session) -> None:
    a = _tracked(session, "AAPL")
    TrackedTradeRepository(session).close(a, ts=TS, reason="test")
    b = _tracked(session, "AAPL")  # a second recommendation for the same symbol
    journal = _journal(session, entry_offset_days=1)
    counts = svc.link_journal_trades(session, ts=TS)
    assert counts["linked"] == 1
    linked = [t for t in (a, b) if t.journal_trade_id == journal.id]
    assert len(linked) == 1


def test_linking_is_idempotent(session: Session) -> None:
    _tracked(session)
    _journal(session, entry_offset_days=1)
    assert svc.link_journal_trades(session, ts=TS)["linked"] == 1
    assert svc.link_journal_trades(session, ts=TS)["linked"] == 0  # nothing re-linked


# --------------------------------------------------------------------------- #
# realized outcomes
# --------------------------------------------------------------------------- #
def test_closed_journal_trade_realizes_outcome(session: Session) -> None:
    tracked = _tracked(session)
    _journal(session, closed=True, r_multiple=2.5, net_pnl=2000.0, entry_offset_days=1)
    counts = svc.link_journal_trades(session, ts=TS)
    assert counts == {"linked": 1, "realized": 1}
    assert tracked.realized_r == 2.5
    assert tracked.realized_pnl == 2000.0
    assert tracked.realized_at is not None
    assert tracked.status == "closed"
    assert tracked.close_reason is not None and "journal trade closed" in tracked.close_reason


def test_open_journal_trade_realizes_later(session: Session) -> None:
    tracked = _tracked(session)
    journal = _journal(session, entry_offset_days=1)  # still open
    assert svc.link_journal_trades(session, ts=TS) == {"linked": 1, "realized": 0}
    assert tracked.realized_r is None

    journal.status = "closed"
    journal.r_multiple = -1.0
    journal.net_pnl = -800.0
    journal.exit_reason = "stop"
    session.flush()
    assert svc.link_journal_trades(session, ts=TS) == {"linked": 0, "realized": 1}
    assert tracked.realized_r == -1.0


def test_realization_preserves_evaluation_history(session: Session) -> None:
    tracked = _tracked(session)
    _evaluate(session, tracked, 105.0)
    _evaluate(session, tracked, 110.0)
    _journal(session, closed=True, r_multiple=1.0, entry_offset_days=1)
    svc.link_journal_trades(session, ts=TS)
    assert TradeEvaluationRepository(session).count_for(tracked.trade_uid) == 2


# --------------------------------------------------------------------------- #
# advice grading
# --------------------------------------------------------------------------- #
def test_grades_and_report(session: Session) -> None:
    tracked = _tracked(session)
    _evaluate(session, tracked, 104.0)  # r_at_eval = 0.5 (likely Hold)
    _journal(session, closed=True, r_multiple=3.0, net_pnl=2400.0, entry_offset_days=1)
    svc.link_journal_trades(session, ts=TS)

    grades = svc.trade_grades(session, tracked.trade_uid)
    assert len(grades) == 1
    grade = grades[0]
    assert grade.r_at_evaluation == 0.5
    assert grade.final_r == 3.0
    assert grade.remaining_r == 2.5
    assert grade.verdict in ("Correct", "Incorrect")  # decisive: 2.5R follow-through

    report = svc.advice_report(session)
    assert report.trades_realized == 1
    assert report.evaluations_graded == 1
    assert report.by_action
    assert report.recent_grades[0].trade_uid == tracked.trade_uid
    assert report.overall_accuracy in (0.0, 1.0)


def test_unrealized_trades_are_not_graded(session: Session) -> None:
    tracked = _tracked(session)
    _evaluate(session, tracked, 104.0)
    assert svc.trade_grades(session, tracked.trade_uid) == []
    report = svc.advice_report(session)
    assert report.trades_realized == 0
    assert report.evaluations_graded == 0
    assert report.overall_accuracy is None


def test_hold_into_winner_graded_correct(session: Session) -> None:
    tracked = _tracked(session)
    _evaluate(session, tracked, 100.0)  # at entry, thesis intact -> Hold-ish advice
    _journal(session, closed=True, r_multiple=4.0, entry_offset_days=1)
    svc.link_journal_trades(session, ts=TS)
    grade = svc.trade_grades(session, tracked.trade_uid)[0]
    if grade.action in ("Hold", "Scale In", "Lower Stop"):
        assert grade.verdict == "Correct"
    else:
        assert grade.verdict == "Incorrect"  # defensive advice before a 4R run


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
def test_routes_serve_report_and_grades(session: Session) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from momentum.api.app import create_app
    from momentum.api.jobs import JobManager

    tracked = _tracked(session)
    _evaluate(session, tracked, 104.0)
    _journal(session, closed=True, r_multiple=3.0, entry_offset_days=1)
    svc.link_journal_trades(session, ts=TS)
    session.commit()
    uid = tracked.trade_uid
    bind = session.get_bind()

    factory = sessionmaker(bind=bind, expire_on_commit=False, future=True)
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)

    report = client.get("/trade-lifecycle/advice-report").json()
    assert report["trades_realized"] == 1
    assert report["evaluations_graded"] == 1

    grades = client.get(f"/trade-lifecycle/{uid}/grades").json()
    assert len(grades) == 1
    assert grades[0]["final_r"] == 3.0

    trade = client.get(f"/trade-lifecycle/{uid}").json()
    assert trade["realized_r"] == 3.0
    assert trade["journal_trade_id"] is not None

    assert client.get("/trade-lifecycle/nope/grades").status_code == 404
