"""End-to-end automatic trade management: scan → take → target scale-out →
final-target close → stop close, with realized outcomes, reports and alerts.

Each test drives the REAL scan pipeline (stub provider with controllable last
prices) so what is proven here is exactly what the daemon does every cycle
while the market is open.
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
from momentum.persistence.models import Activity, Alert, AuditLog, Base
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.universe.screener import MomentumScanner

SYMBOLS = [f"SYM{i:03d}" for i in range(8)]
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


class PricedProvider:
    """Deterministic bars whose FINAL close can be pinned per symbol."""

    name = "stub"

    def __init__(self) -> None:
        self.last: dict[str, float] = {}
        self.intraday: dict[str, float] = {}  # 1-minute last print, when set

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        from momentum.data.schema import Timeframe

        if Timeframe.MINUTE in a:
            pinned = self.intraday.get(symbol)
            if pinned is None:
                return pd.DataFrame()
            idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=3, freq="min")
            return pd.DataFrame(
                {
                    "open": [pinned] * 3,
                    "high": [pinned] * 3,
                    "low": [pinned] * 3,
                    "close": [pinned] * 3,
                    "volume": [10_000.0] * 3,
                },
                index=idx,
            )
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) % 9999)
        close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.02, 300))
        pinned = self.last.get(symbol)
        if pinned is not None:
            close[-1] = pinned
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


def _scan(
    factory: sessionmaker[Session], provider: PricedProvider, symbols: list[str] | None = None
) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=provider,
        scanner=MomentumScanner(),
        symbols=symbols or SYMBOLS,
        sectors={s: "Technology" for s in SYMBOLS},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Default",
        market_state="regular",
    )


def _take_one(factory: sessionmaker[Session]) -> tuple[str, str, list[dict[str, Any]], float]:
    """Take the first tracked trade on paper; return (symbol, uid, targets, stop)."""
    with factory() as s:
        tracked = TrackedTradeRepository(s).open_trades()
        assert tracked, "the scan should create tracked trades from its plans"
        trade = tracked[0]
        take = svc.take_trade(s, trade.symbol, ts=NOW)
        assert take["ok"] is True, take
        return trade.symbol, trade.trade_uid, list(trade.targets or []), trade.stop_price


def test_take_profit_scales_then_closes_at_final_target(factory: sessionmaker[Session]) -> None:
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, targets, _stop = _take_one(factory)
    assert len(targets) >= 2

    # Next cycle: price pops through target 1 → partial scale-out, stays open.
    provider.last[symbol] = float(targets[0]["price"]) * 1.001
    result = _scan(factory, provider)
    assert result["trades_scaled_out"] == 1
    assert result["trades_auto_closed"] == 0
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "open"
        assert trade.targets is not None and trade.targets[0].get("hit") is True
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "open"
        assert journal.scaled_out_quantity > 0
        assert journal.scaled_out_pnl > 0

    # Same price again: the hit target must NOT re-fire (idempotent per target).
    again = _scan(factory, provider)
    assert again["trades_scaled_out"] == 0
    assert again["trades_auto_closed"] == 0

    # Final target reached → remainder closed, outcome realized, advice gradable.
    provider.last[symbol] = float(targets[-1]["price"]) * 1.001
    final = _scan(factory, provider)
    assert final["trades_auto_closed"] == 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        assert trade.realized_r is not None and trade.realized_r > 0
        assert trade.realized_pnl is not None and trade.realized_pnl > 0
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "closed"
        assert journal.exit_reason == "target"


def test_stop_loss_closes_and_realizes(factory: sessionmaker[Session]) -> None:
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, _targets, stop = _take_one(factory)

    provider.last[symbol] = stop * 0.99
    result = _scan(factory, provider)
    assert result["trades_auto_closed"] == 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        assert "stop" in (trade.close_reason or "")
        assert trade.realized_r is not None and trade.realized_r < 0
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "closed"
        assert journal.exit_reason == "stop"


def test_management_produces_report_alert_activity_audit(
    factory: sessionmaker[Session],
) -> None:
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, _targets, stop = _take_one(factory)
    provider.last[symbol] = stop * 0.99
    _scan(factory, provider)

    with factory() as s:
        # The how-and-why report.
        report = svc.management_report(s, uid)
        assert report is not None
        assert report.status == "closed"
        assert len(report.events) == 1
        event = report.events[0]
        assert event.kind == "stop_loss"
        assert "protective stop" in event.analysis
        assert event.evidence["stop_price"] == pytest.approx(stop)
        assert "stop" in report.summary and f"{report.realized_r:+.2f}R" in report.summary

        # Notification: a deduped critical alert for this symbol's stop.
        alerts = list(
            s.scalars(select(Alert).where(Alert.kind == "trade_managed", Alert.symbol == symbol))
        )
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"
        assert alerts[0].dedupe_key.startswith(f"managed:{symbol}:")

        # Activity feed + audit trail carry the same event.
        acts = list(
            s.scalars(
                select(Activity).where(Activity.category == "management", Activity.symbol == symbol)
            )
        )
        assert len(acts) == 1
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "tracked_trade", AuditLog.symbol == symbol
                )
            )
        )
        assert audits, "management must be audit-logged"


def test_zero_candidate_scan_still_manages_open_trades(
    factory: sessionmaker[Session],
) -> None:
    """A scan that surfaces nothing new must still watch the trades we hold."""
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, _targets, stop = _take_one(factory)

    # Crash every symbol: momentum collapses → no candidates pass the scan,
    # and every open tracked trade (including the one we took) breaches its
    # stop on the same cycle — the crash must not blind the manager.
    for s in SYMBOLS:
        provider.last[s] = 5.0
    result = _scan(factory, provider)
    assert result["candidates"] == 0
    assert result["trades_reevaluated"] >= 1
    assert result["trades_auto_closed"] >= 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "closed"
        assert TrackedTradeRepository(s).open_trades() == []  # nothing left unmanaged


def test_held_symbol_outside_universe_is_still_managed(
    factory: sessionmaker[Session],
) -> None:
    """Switching universes must not orphan an open position."""
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, _targets, stop = _take_one(factory)

    # Next scan runs on a universe that does NOT include the held symbol.
    other = [s for s in SYMBOLS if s != symbol][:4]
    provider.last[symbol] = stop * 0.99
    result = _scan(factory, provider, symbols=other)
    assert result["trades_reevaluated"] >= 1
    assert result["trades_auto_closed"] == 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"


def test_intraday_price_manages_before_the_daily_bar_shows_it(
    factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    """Market open: a stop breached intraday closes NOW, not at the daily print."""
    from momentum.daemon import market_state as ms

    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, _targets, stop = _take_one(factory)

    # Daily bar still ABOVE the stop; the 1-minute feed has already breached it.
    monkeypatch.setattr(
        "momentum.api.actions._intraday_last_prices",
        lambda *_a, **_k: {symbol: stop * 0.99},
    )
    result = _scan(factory, provider)
    assert result["trades_auto_closed"] >= 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "closed"
        assert journal.exit_price == pytest.approx(stop * 0.99, rel=1e-4)
    assert ms  # imported to prove the module is available for state resolution
