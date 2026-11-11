"""End-to-end automatic trade management: scan → take → hold through strength →
trend exit / stop close, with realized outcomes, reports and alerts.

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


def test_price_through_the_milestones_sells_nothing(factory: sessionmaker[Session]) -> None:
    """The strategy has no profit target: a winner is simply held."""
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, targets, _stop = _take_one(factory)
    assert len(targets) >= 2

    for level in (targets[0], targets[-1]):
        provider.last[symbol] = float(level["price"]) * 1.001
        result = _scan(factory, provider)
        assert result["trades_scaled_out"] == 0
        assert result["trades_auto_closed"] == 0
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "open"
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "open"
        assert journal.scaled_out_quantity == 0
        assert not list(s.scalars(select(Alert).where(Alert.kind == "trade_managed")))


def test_milestone_selling_is_still_available_when_switched_on(
    factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    """Opt-in legacy behaviour: scale out at T1, close the rest at the last milestone."""
    from momentum.trade_lifecycle.config import TradeLifecycleConfig

    monkeypatch.setattr(svc, "default_config", lambda: TradeLifecycleConfig(auto_take_profit=True))
    provider = PricedProvider()
    _scan(factory, provider)
    symbol, uid, targets, _stop = _take_one(factory)

    provider.last[symbol] = float(targets[0]["price"]) * 1.001
    result = _scan(factory, provider)
    assert result["trades_scaled_out"] == 1 and result["trades_auto_closed"] == 0
    again = _scan(factory, provider)  # the hit milestone must not re-fire
    assert again["trades_scaled_out"] == 0

    provider.last[symbol] = float(targets[-1]["price"]) * 1.001
    final = _scan(factory, provider)
    assert final["trades_auto_closed"] == 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        assert trade.realized_r is not None and trade.realized_r > 0
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.exit_reason == "target"


BASE = "BASE"


class BaseBreakoutProvider(PricedProvider):
    """Adds one crafted symbol: a strong run-up, a 50-bar choppy base just under
    the high, then a breakout close. Its 50-day low (the base's floor, ~96) sits
    well above the 3×ATR stop (~93), so a close between the two is a trend exit."""

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        from momentum.data.schema import Timeframe

        if symbol != BASE or Timeframe.MINUTE in a:
            return super().get_bars(symbol, *a, **k)
        run_up = np.geomspace(20.0, 100.0, 250)
        base = np.where(np.arange(49) % 2 == 0, 96.5, 99.5)
        close = np.concatenate([run_up, base, [103.0]])
        pinned = self.last.get(symbol)
        if pinned is not None:
            close[-1] = pinned
        idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=300, freq="B")
        return pd.DataFrame(
            {
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": np.full(300, 3_000_000.0),
            },
            index=idx,
        )


def _take_base(
    factory: sessionmaker[Session], provider: PricedProvider
) -> tuple[str, float, float]:
    """Take the crafted breakout; return (uid, exit_level, stop)."""
    with factory() as s:
        tracked = TrackedTradeRepository(s).open_for_symbol(BASE)
        assert tracked is not None, "the crafted breakout must be a scan candidate"
        prior_low = float(provider.get_bars(BASE)["low"].iloc[-51:-1].min())
        assert prior_low > tracked.stop_price * 1.02  # the scenario's premise
        take = svc.take_trade(s, BASE, ts=NOW)
        assert take["ok"] is True, take
        return tracked.trade_uid, prior_low, tracked.stop_price


def test_trend_exit_closes_and_realizes(factory: sessionmaker[Session]) -> None:
    """A daily close below the prior 50-day low sells the position — the
    strategy's exit — with its own report, alert and audit trail."""
    provider = BaseBreakoutProvider()
    universe = [*SYMBOLS, BASE]
    _scan(factory, provider, symbols=universe)
    symbol = BASE
    uid, exit_level, stop = _take_base(factory, provider)

    provider.last[symbol] = (exit_level + stop) / 2.0  # below the 50-day low, above the stop
    result = _scan(factory, provider, symbols=universe)
    assert result["trades_auto_closed"] >= 1
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        assert "trend exit" in (trade.close_reason or "")
        journal = s.get(Trade, trade.journal_trade_id)
        assert journal is not None and journal.status == "closed"
        assert journal.exit_reason == "trend_exit"
        report = svc.management_report(s, uid)
        assert report is not None and report.events[-1].kind == "trend_exit"
        assert "50-day low" in report.events[-1].analysis
        alerts = list(
            s.scalars(select(Alert).where(Alert.kind == "trade_managed", Alert.symbol == symbol))
        )
        assert len(alerts) == 1 and "trend exit" in alerts[0].title


def test_untaken_recommendations_raise_no_alerts(factory: sessionmaker[Session]) -> None:
    """A recommendation nobody took is not a position: when price invalidates
    it, it is retired quietly — no alert, no activity, no audit event."""
    provider = PricedProvider()
    _scan(factory, provider)
    with factory() as s:
        tracked = TrackedTradeRepository(s).open_trades()
        assert tracked and all(t.journal_trade_id is None for t in tracked)
        victim = tracked[0]
        symbol, uid, stop = victim.symbol, victim.trade_uid, victim.stop_price

    provider.last[symbol] = stop * 0.97
    _scan(factory, provider)
    with factory() as s:
        trade = TrackedTradeRepository(s).get_by_uid(uid)
        assert trade is not None and trade.status == "closed"
        assert "recommendation expired" in (trade.close_reason or "")
        assert not list(s.scalars(select(Alert).where(Alert.kind == "trade_managed")))
        assert not list(s.scalars(select(Alert).where(Alert.kind == "concentration")))
        assert not list(
            s.scalars(
                select(Activity).where(Activity.category == "management", Activity.symbol == symbol)
            )
        )


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
