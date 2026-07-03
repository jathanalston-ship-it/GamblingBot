"""Committee service + route tests: minutes are persisted and immutable."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import committee_service
from momentum.api.app import create_app
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.persistence.repositories.committee import CommitteeMeetingRepository


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def test_convene_persists_minutes(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        decision = committee_service.convene_and_persist(session, "aapl", context="entry")
        session.commit()
        assert decision.symbol == "AAPL"
        rows = CommitteeMeetingRepository(session).recent(symbol="AAPL")
        assert len(rows) == 1
        row = rows[0]
        assert row.action == decision.action.value
        assert len(row.votes) == 7
        assert row.narrative
        with pytest.raises(TypeError, match="append-only"):
            CommitteeMeetingRepository(session).delete(row)


def test_meetings_accumulate_never_replace(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        committee_service.convene_and_persist(session, "AAPL", context="entry")
        committee_service.convene_and_persist(session, "AAPL", context="manage")
        session.commit()
        rows = CommitteeMeetingRepository(session).recent(symbol="AAPL")
        assert len(rows) == 2
        assert {r.context for r in rows} == {"entry", "manage"}


def test_committee_routes(factory: sessionmaker[Session]) -> None:
    client = TestClient(create_app(session_factory=factory))
    convened = client.post("/committee/convene/NVDA").json()
    assert convened["symbol"] == "NVDA"
    assert len(convened["votes"]) == 7
    meetings = client.get("/committee/meetings?symbol=NVDA").json()
    assert len(meetings) == 1
    uid = meetings[0]["meeting_uid"]
    detail = client.get(f"/committee/meetings/{uid}").json()
    assert detail["narrative"]
    assert client.get("/committee/meetings/nope").status_code == 404


def test_portfolio_manager_member_sees_the_book(factory: sessionmaker[Session]) -> None:
    """An oversized open position turns the PM's abstain into a REDUCE vote."""
    import datetime as dt

    from momentum.persistence.models import PortfolioSnapshot, Trade

    with factory() as session:
        session.add(
            Trade(
                run_id="manual",
                symbol="HUGE",
                direction="long",
                status="open",
                entry_ts=dt.datetime(2026, 6, 1, 15, tzinfo=dt.UTC),
                entry_price=100.0,
                quantity=400,  # $40k of a $100k book -> 40% single-name
                initial_stop=95.0,
                initial_risk=2000.0,
            )
        )
        session.add(
            PortfolioSnapshot(
                run_id="manual",
                as_of=dt.date(2026, 7, 1),
                session_date=dt.date(2026, 7, 1),
                equity=100_000.0,
                cash=60_000.0,
            )
        )
        session.commit()

        decision = committee_service.convene_and_persist(session, "HUGE", context="manage")
        session.commit()
        pm = next(v for v in decision.votes if v.member == "Portfolio Manager")
        assert pm.confidence > 0
        assert pm.choice.value == "reduce"
        assert "40%" in pm.justification
