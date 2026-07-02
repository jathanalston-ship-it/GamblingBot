"""Manual trade actions: Take / Track / Close — the buttons that connect the
research pipeline to the execution + learning half.

Take opens a paper journal trade from the symbol's plan and links it to the
tracked thesis; Close realizes the outcome, which grades every piece of advice
the trade received. Proven end-to-end on a live-shaped scan.
"""

from __future__ import annotations

import datetime as dt
import zlib
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, trade_lifecycle_service as svc
from momentum.persistence.models import Base, SetupLifecycle, TradePlan
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.universe.screener import MomentumScanner

SYMBOLS = [f"SYM{i:03d}" for i in range(12)]
NOW = dt.datetime.now(tz=dt.UTC)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


class StubProvider:
    name = "stub"

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) % 9999)
        close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.02, 300))
        idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=300, freq="B")
        opens = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.02,
                "low": np.minimum(opens, close) * 0.98,
                "close": close,
                "volume": np.full(300, 3_000_000.0),
            },
            index=idx,
        )


def _scan(factory: sessionmaker[Session]) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=MomentumScanner(),
        symbols=SYMBOLS,
        sectors={s: "Technology" for s in SYMBOLS},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Default",
        market_state="regular",
    )


def _planned_symbol(factory: sessionmaker[Session]) -> str:
    with factory() as s:
        plan = s.scalars(select(TradePlan).limit(1)).one()
        return plan.symbol


# --------------------------------------------------------------------------- #
# take
# --------------------------------------------------------------------------- #
def test_take_trade_opens_journal_and_links(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    symbol = _planned_symbol(factory)
    with factory() as s:
        result = svc.take_trade(s, symbol, ts=NOW)
        assert result["ok"] is True
        assert result["shares"] > 0
        assert result["linked"] >= 0

        journal = s.get(Trade, result["journal_trade_id"])
        assert journal is not None
        assert journal.status == "open"
        assert journal.entry_reason == "manual"
        assert journal.initial_stop == result["stop_price"]

        tracked = TrackedTradeRepository(s).open_for_symbol(symbol)
        assert tracked is not None
        assert tracked.journal_trade_id == journal.id  # take → track → link, one click


def test_take_twice_is_refused(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    symbol = _planned_symbol(factory)
    with factory() as s:
        assert svc.take_trade(s, symbol, ts=NOW)["ok"] is True
        second = svc.take_trade(s, symbol, ts=NOW)
        assert second["ok"] is False
        assert "already" in second["error"]


def test_take_unknown_symbol_fails_helpfully(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as s:
        result = svc.take_trade(s, "NOPE", ts=NOW)
        assert result["ok"] is False
        assert "no trade plan" in result["error"]


# --------------------------------------------------------------------------- #
# track
# --------------------------------------------------------------------------- #
def test_track_symbol_is_idempotent(factory: sessionmaker[Session]) -> None:
    _scan(factory)  # auto-tracks every recommendation
    symbol = _planned_symbol(factory)
    with factory() as s:
        result = svc.track_symbol(s, symbol, ts=NOW)
        assert result["ok"] is True
        assert result["created"] is False  # the scan already tracked it
        assert TrackedTradeRepository(s).count() == len(TrackedTradeRepository(s).open_trades())


# --------------------------------------------------------------------------- #
# close → realized outcome → advice grades
# --------------------------------------------------------------------------- #
def test_close_realizes_and_grades(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    symbol = _planned_symbol(factory)
    with factory() as s:
        take = svc.take_trade(s, symbol, ts=NOW)
        assert take["ok"] is True
        entry = take["entry_price"]

        close = svc.close_manual_trade(
            s, symbol=symbol, price=entry * 1.2, ts=NOW + dt.timedelta(days=5)
        )
        assert close["ok"] is True
        assert close["exit_price"] == pytest.approx(entry * 1.2)
        assert close["realized_r"] is not None and close["realized_r"] > 0

        tracked = TrackedTradeRepository(s).get_by_uid(close["trade_uid"])
        assert tracked is not None
        assert tracked.status == "closed"
        assert tracked.realized_r == close["realized_r"]

        # the advice the trade received is now graded with hindsight
        grades = svc.trade_grades(s, close["trade_uid"])
        assert grades  # the scan's first evaluation got graded
        report = svc.advice_report(s)
        assert report.trades_realized == 1


def test_close_without_take_is_refused(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    symbol = _planned_symbol(factory)
    with factory() as s:
        result = svc.close_manual_trade(s, symbol=symbol, ts=NOW)
        assert result["ok"] is False
        assert "never taken" in result["error"]


def test_close_uses_last_known_price(factory: sessionmaker[Session]) -> None:
    _scan(factory)  # the scan evaluated every tracked trade → a known price exists
    symbol = _planned_symbol(factory)
    with factory() as s:
        svc.take_trade(s, symbol, ts=NOW)
        close = svc.close_manual_trade(s, symbol=symbol, ts=NOW)  # no explicit price
        assert close["ok"] is True
        assert close["exit_price"] > 0


# --------------------------------------------------------------------------- #
# audit fix: scans now populate setup lifecycles
# --------------------------------------------------------------------------- #
def test_scan_refreshes_setup_lifecycles(factory: sessionmaker[Session]) -> None:
    result = _scan(factory)
    assert result["lifecycles_refreshed"] > 0
    with factory() as s:
        assert s.scalars(select(SetupLifecycle).limit(1)).first() is not None


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
def test_routes(factory: sessionmaker[Session]) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app
    from momentum.api.jobs import JobManager

    _scan(factory)
    symbol = _planned_symbol(factory)

    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)

    taken = client.post("/actions/take-trade", json={"symbol": symbol}).json()
    assert taken["ok"] is True

    tracked = client.post("/actions/track-trade", json={"symbol": symbol}).json()
    assert tracked["ok"] is True and tracked["created"] is False

    closed = client.post("/actions/close-trade", json={"symbol": symbol}).json()
    assert closed["ok"] is True

    assert client.post("/actions/take-trade", json={}).status_code == 422
    assert client.post("/actions/close-trade", json={}).status_code == 422
