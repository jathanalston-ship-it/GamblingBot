"""Thesis journal + management analytics over tracked trades.

The journal turns the append-only evaluation history into the trade's story
(opened → evaluations → exited); management analytics grade the management
logic itself. Both are derived on demand from persisted rows.
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


def _tracked(session: Session, symbol: str = "NVDA"):  # type: ignore[no-untyped-def]
    row = TrackedTradeRepository(session).create_from_spec(
        TradeSpec(
            symbol=symbol,
            recommended_at=TS,
            run_id="scan-1",
            instrument="shares",
            quantity=100,
            entry_price=100.0,
            stop_price=92.0,
            targets=(),
            conviction_score=91.0,
            conviction_band="extreme",
            regime="bull",
            sector="Technology",
            thesis="new all-time high on strong volume",
            entry_atr=2.0,
            sector_rs=0.8,
            momentum_score=70.0,
            analog_expectancy_r=0.5,
        )
    )
    assert row is not None
    return row


def _evaluate(
    session: Session,
    row,  # type: ignore[no-untyped-def]
    *,
    price: float,
    conviction: float,
    days: int,
) -> None:
    ts = TS + dt.timedelta(days=days)
    evaluation = ThesisReevaluationEngine().evaluate(
        EvaluationInputs(
            symbol=row.symbol,
            entry_price=row.entry_price,
            stop_price=row.stop_price,
            price=price,
            original_conviction=row.conviction_score,
            current_conviction=conviction,
            regime_at_entry=row.regime,
            regime_now="bull",
            days_held=float(days),
            analog_expectancy_now=0.5,
            analog_sample_size=20,
        )
    )
    TradeEvaluationRepository(session).append(row.trade_uid, evaluation, run_id=None, ts=ts)
    TrackedTradeRepository(session).apply_evaluation(row, evaluation, ts=ts)


# --------------------------------------------------------------------------- #
# journal
# --------------------------------------------------------------------------- #
def test_journal_tells_the_whole_story(session: Session) -> None:
    row = _tracked(session)
    _evaluate(session, row, price=104.0, conviction=91.0, days=1)
    _evaluate(session, row, price=110.0, conviction=88.0, days=4)
    _journal_trade = Trade(
        symbol="NVDA",
        direction="long",
        entry_ts=TS + dt.timedelta(days=1),
        entry_price=100.0,
        quantity=100,
        status="closed",
        exit_ts=TS + dt.timedelta(days=17),
        exit_price=116.0,
        r_multiple=2.0,
        net_pnl=1600.0,
        exit_reason="target",
    )
    session.add(_journal_trade)
    session.flush()
    svc.link_journal_trades(session, ts=TS + dt.timedelta(days=17))

    entries = svc.trade_journal(session, row.trade_uid)
    labels = [e.label for e in entries]
    assert labels[0] == "Opened"
    assert labels[-1] == "Exited"
    assert len(entries) == 4  # opened + 2 evaluations + exited

    opened = entries[0]
    assert opened.detail is not None and "Conviction 91" in opened.detail
    assert opened.at == TS.isoformat()

    exited = entries[-1]
    assert exited.detail is not None and "+2.00R" in exited.detail

    # every evaluation entry carries its health + a data-backed detail
    for entry in entries[1:-1]:
        assert entry.health_score is not None
        assert entry.detail


def test_journal_is_chronological_and_append_only(session: Session) -> None:
    row = _tracked(session)
    for day in range(1, 6):
        _evaluate(session, row, price=100.0 + day, conviction=91.0 - day, days=day)
    entries = svc.trade_journal(session, row.trade_uid)
    stamps = [e.at for e in entries if e.at]
    assert stamps == sorted(stamps)
    assert len(entries) == 6  # opened + 5 — nothing replaced


def test_journal_missing_trade_is_empty(session: Session) -> None:
    assert svc.trade_journal(session, "nope") == []


# --------------------------------------------------------------------------- #
# management analytics
# --------------------------------------------------------------------------- #
def test_management_analytics_full_surface(session: Session) -> None:
    row = _tracked(session)
    # conviction dips then recovers; health tracked throughout
    for day, conviction in [(1, 91.0), (3, 70.0), (5, 85.0)]:
        _evaluate(session, row, price=104.0, conviction=conviction, days=day)
    journal_trade = Trade(
        symbol="NVDA",
        direction="long",
        entry_ts=TS + dt.timedelta(days=1),
        entry_price=100.0,
        quantity=100,
        status="closed",
        exit_ts=TS + dt.timedelta(days=10),
        exit_price=124.0,
        r_multiple=3.0,
        net_pnl=2400.0,
        exit_reason="target",
    )
    session.add(journal_trade)
    session.flush()
    svc.link_journal_trades(session, ts=TS + dt.timedelta(days=10))

    report = svc.management_analytics(session)
    assert report.trades_tracked == 1
    assert report.avg_conviction_decay == -6.0  # 85 - 91
    assert report.avg_trade_health is not None and 0 < report.avg_trade_health <= 100
    assert report.avg_holding_period_days is not None and report.avg_holding_period_days > 0
    assert report.max_thesis_age_days is not None and report.max_thesis_age_days >= 5.0
    assert report.avg_conviction_recovery == 15.0  # 85 - 70 rebound
    assert report.avg_health_before_exit is not None
    assert report.most_successful_health is not None
    assert report.most_successful_health["avg_realized_r"] == 3.0
    assert report.avg_stop_raises is not None and report.avg_stop_lowers is not None


def test_management_analytics_empty(session: Session) -> None:
    report = svc.management_analytics(session)
    assert report.trades_tracked == 0
    assert report.avg_trade_health is None
    assert report.best_exits == [] and report.worst_exits == []


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
def test_routes_serve_journal_and_analytics(session: Session) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from momentum.api.app import create_app
    from momentum.api.jobs import JobManager

    row = _tracked(session)
    _evaluate(session, row, price=104.0, conviction=90.0, days=1)
    session.commit()
    uid = row.trade_uid

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)

    journal = client.get(f"/trade-lifecycle/{uid}/journal").json()
    assert journal[0]["label"] == "Opened"
    assert len(journal) == 2

    analytics = client.get("/trade-lifecycle/management-analytics").json()
    assert analytics["trades_tracked"] == 1

    # evaluations now expose health_score / breakdown / explanation
    evaluations = client.get(f"/trade-lifecycle/{uid}/evaluations").json()
    ev = evaluations[0]
    assert ev["health_score"] is not None
    assert len(ev["health_breakdown"]) == 8
    assert ev["explanation"]["narrative"]

    assert client.get("/trade-lifecycle/nope/journal").status_code == 404
