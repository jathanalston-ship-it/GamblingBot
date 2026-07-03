"""User overrides: applied instantly, always audited, and the bot ADAPTS."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, override_service, trade_lifecycle_service
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import AuditLog, Base, Trade
from momentum.persistence.models.tracked_trade import TrackedTrade
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner
from tests.unit.api.test_actions import StubProvider, _noop

NOW = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture(autouse=True)
def user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))
    return tmp_path


def _scan(factory: sessionmaker[Session], provider: Any = None) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=provider or StubProvider(),
        scanner=MomentumScanner(
            ScannerConfig(
                filters=ScanFilters(
                    min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0
                )
            )
        ),
        symbols=["AAA", "BBB", "CCC"],
        lookback_days=400,
        progress=_noop,
        market_state="regular",
    )


@pytest.fixture
def taken(factory: sessionmaker[Session]) -> str:
    """Scan + take AAA; returns the tracked trade uid."""
    _scan(factory)
    with factory() as session:
        take = trade_lifecycle_service.take_trade(session, "AAA", ts=dt.datetime.now(tz=dt.UTC))
        assert take["ok"], take.get("error")
        uid = session.scalars(
            select(TrackedTrade.trade_uid).where(TrackedTrade.symbol == "AAA")
        ).one()
    return str(uid)


def _audit_overrides(session: Session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.event_type == "user_override")))


def test_move_stop_is_applied_audited_and_respected_exactly(
    factory: sessionmaker[Session], taken: str
) -> None:
    with factory() as session:
        tracked = session.scalars(select(TrackedTrade).where(TrackedTrade.symbol == "AAA")).one()
        original_stop = tracked.stop_price
        user_stop = original_stop * 0.90  # user LOWERS the stop — must win

        result = override_service.apply_override(
            session, taken, action="move_stop", price=user_stop, ts=NOW
        )
        assert result["ok"], result.get("error")
        journal = session.get(Trade, tracked.journal_trade_id)
        assert journal is not None and journal.current_stop == pytest.approx(user_stop)
        rows = _audit_overrides(session)
        assert len(rows) == 1 and "moved stop" in rows[0].summary

    # The bot adapts: a price BETWEEN the user stop and the original stop
    # would previously have closed the trade; the user's stop now governs.
    from momentum.trade_lifecycle.auto_manage import decide_management

    between = (user_stop + original_stop) / 2
    decision = decide_management(
        symbol="AAA",
        entry_price=original_stop / 0.9,  # entry above both stops
        stop_price=original_stop,
        price=between,
        targets=(),
        evaluation=None,
        days_held=1.0,
        config=trade_lifecycle_service.default_config(),
        current_stop=user_stop,
    )
    assert decision is None or decision.kind != "stop_loss"  # user stop respected
    below_user = user_stop * 0.99
    breach = decide_management(
        symbol="AAA",
        entry_price=original_stop / 0.9,
        stop_price=original_stop,
        price=below_user,
        targets=(),
        evaluation=None,
        days_held=1.0,
        config=trade_lifecycle_service.default_config(),
        current_stop=user_stop,
    )
    assert breach is not None and breach.kind == "stop_loss"  # ... and still protects


def test_convert_manual_stops_bot_execution(factory: sessionmaker[Session], taken: str) -> None:
    with factory() as session:
        result = override_service.apply_override(session, taken, action="convert_manual", ts=NOW)
        assert result["management_mode"] == "manual"
        assert _audit_overrides(session)

    # A 40% gap through every target: a MANAGED trade would be acted on;
    # the MANUAL trade must remain untouched (bot advises, never acts).
    class Gapped(StubProvider):
        def get_bars(self, symbol: str, *a: Any, **k: Any) -> Any:
            frame = super().get_bars(symbol, *a, **k)
            return frame * 1.4 if not frame.empty else frame

    _scan(factory, Gapped())
    with factory() as session:
        tracked = session.scalars(select(TrackedTrade).where(TrackedTrade.symbol == "AAA")).one()
        assert tracked.status == "open"  # never auto-closed in manual mode
        journal = session.get(Trade, tracked.journal_trade_id)
        assert journal is not None and journal.status == "open"

        # Back to managed: the very next scan acts on the same evidence.
        override_service.apply_override(session, taken, action="convert_managed", ts=NOW)
    _scan(factory, Gapped())
    with factory() as session:
        journal = session.scalars(select(Trade)).one()
        tracked = session.scalars(select(TrackedTrade).where(TrackedTrade.symbol == "AAA")).one()
        acted = (
            journal.status == "closed"
            or (journal.quantity < (tracked.quantity or 0))
            or (journal.current_stop is not None)
        )
        assert acted  # the bot resumed managing immediately


def test_reduce_add_and_close(factory: sessionmaker[Session], taken: str) -> None:
    with factory() as session:
        tracked = session.scalars(select(TrackedTrade).where(TrackedTrade.symbol == "AAA")).one()
        journal = session.get(Trade, tracked.journal_trade_id)
        assert journal is not None
        qty = journal.quantity
        price = journal.entry_price * 1.05

        reduced = override_service.apply_override(
            session, taken, action="reduce", price=price, quantity=max(qty // 2, 1), ts=NOW
        )
        assert reduced["ok"] and reduced["quantity"] == qty - max(qty // 2, 1)

        added = override_service.apply_override(
            session, taken, action="add", price=price, quantity=5, ts=NOW
        )
        assert added["ok"] and added["quantity"] == reduced["quantity"] + 5

        closed = override_service.apply_override(
            session, taken, action="close", price=price, ts=NOW
        )
        assert closed["ok"] and closed["closed"] is True

        journal = session.get(Trade, tracked.journal_trade_id)
        assert journal is not None and journal.status == "closed"
        assert journal.exit_reason == "user_override"
        tracked = session.scalars(select(TrackedTrade).where(TrackedTrade.symbol == "AAA")).one()
        assert tracked.status == "closed"
        assert len(_audit_overrides(session)) == 3  # every override on the record


def test_override_validation_refuses_garbage(factory: sessionmaker[Session], taken: str) -> None:
    with factory() as session:
        assert not override_service.apply_override(session, taken, action="nope")["ok"]
        assert not override_service.apply_override(session, taken, action="move_stop")["ok"]
        assert not override_service.apply_override(session, "ghost", action="close", price=1)["ok"]
        journal_count = session.query(Trade).count()
        assert journal_count == 1  # refused overrides change nothing
        assert _audit_overrides(session) == []  # nothing happened, nothing logged


def test_override_endpoint_over_http(factory: sessionmaker[Session], taken: str) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app

    client = TestClient(create_app(session_factory=factory))
    response = client.post(f"/trade-lifecycle/{taken}/override", json={"action": "convert_manual"})
    assert response.status_code == 200
    assert response.json()["management_mode"] == "manual"
    listed = client.get("/trade-lifecycle").json()
    assert listed[0]["management_mode"] == "manual"
