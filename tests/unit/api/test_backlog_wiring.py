"""Backlog wiring: scans emit signals + audit events; manual takes link the
entry signal; tracked trades carry the options-eligibility instrument."""

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
from momentum.persistence.models import AuditLog, Base, Signal
from momentum.persistence.models.trade import Trade
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.universe.screener import MomentumScanner

SYMBOLS = [f"SYM{i:03d}" for i in range(10)]
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


def test_scan_emits_entry_signals_idempotently(factory: sessionmaker[Session]) -> None:
    first = _scan(factory)
    with factory() as s:
        signals = list(s.scalars(select(Signal).where(Signal.source == "scan")))
    assert len(signals) == first["candidates"]
    assert all(sig.signal_type == "entry" and sig.reference_price for sig in signals)

    _scan(factory)  # same day → same run_id → replaced, not duplicated
    with factory() as s:
        again = list(s.scalars(select(Signal).where(Signal.source == "scan")))
    assert len(again) == len(signals)


def test_scan_is_audit_logged(factory: sessionmaker[Session]) -> None:
    result = _scan(factory)
    with factory() as s:
        events = list(s.scalars(select(AuditLog).where(AuditLog.run_id == result["run_id"])))
    assert events
    assert any("scan" in (e.summary or "") for e in events)


def test_take_trade_links_the_scan_signal(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as s:
        symbol = s.scalars(select(TradePlan.symbol).limit(1)).one()
        take = svc.take_trade(s, symbol, ts=NOW)
        assert take["ok"] is True
        journal = s.get(Trade, take["journal_trade_id"])
        assert journal is not None
        assert journal.entry_signal_id is not None  # Signal Eval can grade this trade
        signal = s.get(Signal, journal.entry_signal_id)
        assert signal is not None and signal.symbol == symbol


def test_tracked_trades_carry_an_instrument_verdict(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as s:
        for trade in TrackedTradeRepository(s).open_trades():
            assert trade.instrument in ("shares", "options")


def test_cli_provider_flag_names() -> None:
    import typer

    from momentum.cli.main import _make_provider

    assert _make_provider("yahoo").__class__.__name__ == "YahooProvider"
    with pytest.raises(typer.BadParameter):
        _make_provider("bloomberg")


# --------------------------------------------------------------------------- #
# /bars endpoint + mark-to-market (backlog: charts + live valuation)
# --------------------------------------------------------------------------- #
def test_bars_endpoint_cache_and_live(factory: sessionmaker[Session], tmp_path: Any) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app
    from momentum.api.jobs import JobManager
    from momentum.data.cache import BarCache
    from momentum.data.schema import Timeframe

    provider = StubProvider()
    cache = BarCache(str(tmp_path / "bars"))
    cache.write("CACHED", Timeframe.DAY, provider.get_bars("CACHED"))

    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    app.state.provider_factory = lambda: provider
    client = TestClient(app)

    cached = client.get("/bars/CACHED?days=90").json()
    assert cached["source"] == "cache"
    assert len(cached["bars"]) > 30
    first = cached["bars"][0]
    assert {"ts", "open", "high", "low", "close"} <= set(first)

    live = client.get("/bars/FRESH?days=90").json()
    assert live["source"] == "live"
    assert client.get("/bars/FRESH?days=90").json()["source"] == "cache"  # now cached


def test_open_trades_are_marked_to_market(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as s:
        symbol = s.scalars(select(TradePlan.symbol).limit(1)).one()
        take = svc.take_trade(s, symbol, ts=NOW)
        assert take["ok"] is True
        rows = svc.list_trades(s, status="open", symbol=symbol)
    assert rows
    trade = rows[0]
    assert trade.last_price is not None and trade.last_price > 0
    assert trade.unrealized_r is not None
    assert trade.distance_to_stop_pct is not None and trade.distance_to_stop_pct > 0
