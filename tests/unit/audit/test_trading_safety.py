"""Trading-safety audit — the $250k pretence, executed.

Every hazard on the safety checklist gets an executed attack: duplicate
orders (sequential AND concurrent), duplicate scans, duplicate trade
management, race conditions between pipelines, stale-data decisions,
missing stops, invalid sizing, negative buying power, impossible fills,
infinite loops, unbounded memory, scheduler drift and orphaned workers.

Stress = seeded randomness at volume; soak = thousands of iterations with
bounded-memory assertions; concurrency = real threads on a file-backed
database (the desktop deployment's actual engine).
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, automation_state
from momentum.api.trading_mutex import TradingPipelineBusyError
from momentum.brokerage import PaperBrokerage, Quote
from momentum.brokerage.execution_sim import ExecutionSimulator
from momentum.brokerage.types import OrderTicket
from momentum.core.enums import OrderType, Side, TimeInForce
from momentum.daemon import DaemonConfig, MarketDaemon, MarketState
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ConvictionScore, Trade
from momentum.persistence.models.broker import BrokerOrderRow
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner
from tests.unit.api.test_actions import StubProvider, _noop

ET = ZoneInfo("America/New_York")
WEDNESDAY = dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.UTC)


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def file_factory(tmp_path: Path) -> sessionmaker[Session]:
    """A real file-backed engine — what the desktop app actually runs on."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'safety.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture(autouse=True)
def user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))
    return tmp_path


def _relaxed() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


def _scan(
    factory: sessionmaker[Session],
    provider: Any = None,
    *,
    market_state: str = "regular",
) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=provider or StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB", "CCC"],
        lookback_days=400,
        progress=_noop,
        market_state=market_state,
    )


def _enable_autopilot(user_dir: Path, **extra: Any) -> None:
    import yaml

    autopilot = {"enabled": True, "min_conviction_score": 0, "max_entries_per_cycle": 5, **extra}
    (user_dir / "settings.yaml").write_text(yaml.safe_dump({"autopilot": autopilot}))


# --------------------------------------------------------------------------- #
# duplicate orders
# --------------------------------------------------------------------------- #
def _ticket(client_order_id: str, quantity: int = 10) -> OrderTicket:
    return OrderTicket(
        client_order_id=client_order_id,
        account_id="primary",
        symbol="AAPL",
        side=Side.LONG,
        quantity=quantity,
    )


def test_duplicate_client_order_id_never_double_orders(
    factory: sessionmaker[Session],
) -> None:
    broker = PaperBrokerage(factory, clock=lambda: WEDNESDAY)
    first = broker.place_order(_ticket("dup-1"))
    second = broker.place_order(_ticket("dup-1", quantity=999))  # replay w/ different size
    assert second.order_id == first.order_id
    assert second.quantity == first.quantity  # the original order wins, always
    with factory() as session:
        assert session.query(BrokerOrderRow).count() == 1


def test_concurrent_duplicate_orders_keep_exactly_one(
    file_factory: sessionmaker[Session],
) -> None:
    """8 threads race the same client_order_id: the venue must keep ONE order."""
    broker = PaperBrokerage(file_factory, clock=lambda: WEDNESDAY)
    broker.ensure_account("primary")
    barrier = threading.Barrier(8)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            barrier.wait(timeout=10.0)
            view = broker.place_order(_ticket("race-1"))
            outcomes.append(view.order_id)
        except BaseException as exc:  # noqa: BLE001 — collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=submit, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"unexpected errors under duplicate race: {errors!r}"
    assert set(outcomes) == {"race-1"}
    with file_factory() as session:
        rows = session.query(BrokerOrderRow).filter_by(order_id="race-1").all()
        assert len(rows) == 1  # the unique index + race absorption held


# --------------------------------------------------------------------------- #
# duplicate / concurrent scans
# --------------------------------------------------------------------------- #
class BlockingProvider(StubProvider):
    """Parks the first scan inside the provider so a second can race it."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        self.entered.set()
        assert self.release.wait(timeout=30.0), "test never released the provider"
        return super().get_bars(symbol, *a, **k)


def test_concurrent_scans_are_refused_not_interleaved(
    factory: sessionmaker[Session],
) -> None:
    """While one scan runs, a second scan (daemon vs manual) is REFUSED —
    two writers can never interleave on the same run_id."""
    provider = BlockingProvider()
    first_result: dict[str, Any] = {}

    def first() -> None:
        first_result.update(_scan(factory, provider))

    thread = threading.Thread(target=first, daemon=True)
    thread.start()
    assert provider.entered.wait(timeout=10.0)

    with pytest.raises(TradingPipelineBusyError, match="'scan' is already running"):
        _scan(factory)

    provider.release.set()
    thread.join(timeout=60.0)
    assert first_result["candidates"] >= 1  # the refusal never hurt the winner
    assert _scan(factory)["candidates"] >= 1  # and the mutex was released


def test_manual_trade_actions_are_refused_mid_scan(
    factory: sessionmaker[Session],
) -> None:
    """A Take clicked mid-scan is refused (409 at the route) — the scan may be
    managing that very symbol at that instant."""
    from momentum.api.trading_mutex import exclusive

    provider = BlockingProvider()
    thread = threading.Thread(target=lambda: _scan(factory, provider), daemon=True)
    thread.start()
    assert provider.entered.wait(timeout=10.0)
    with pytest.raises(TradingPipelineBusyError):
        with exclusive("take-trade"):
            pytest.fail("take-trade must not be granted mid-scan")
    provider.release.set()
    thread.join(timeout=60.0)


# --------------------------------------------------------------------------- #
# duplicate trade management + stale data + stops
# --------------------------------------------------------------------------- #
class GappedProvider(StubProvider):
    """The same bars, gapped up — breaches stops-to-targets deterministically."""

    def __init__(self, factor: float) -> None:
        super().__init__()
        self.factor = factor

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        frame = super().get_bars(symbol, *a, **k)
        return frame * self.factor if not frame.empty else frame


def _journal_snapshot(factory: sessionmaker[Session]) -> list[tuple[Any, ...]]:
    with factory() as session:
        return [
            (t.symbol, t.status, t.quantity, t.exit_price, t.current_stop)
            for t in session.query(Trade).order_by(Trade.id).all()
        ]


def test_repeat_management_converges_and_never_repeats_an_action(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    """Management is one action per cycle BY DESIGN, so repeat scans on a 35%
    gap sequence distinct actions (scale-out → next target → stop raise) —
    but each action fires at most ONCE: quantity only ever falls, stops only
    ever tighten, closes stay closed, and the whole book reaches a fixed
    point instead of trading forever on unchanged data."""
    _enable_autopilot(user_dir)
    entered = _scan(factory)
    assert entered["autopilot_entries"] >= 1
    # Freeze entries: from here on, only MANAGEMENT may touch the book.
    _enable_autopilot(user_dir, enabled=False)

    gapped = GappedProvider(1.35)
    previous = _journal_snapshot(factory)
    fixed_point = False
    for _ in range(8):  # far more cycles than distinct actions exist
        _scan(factory, gapped)
        current = _journal_snapshot(factory)
        for before, after in zip(previous, current, strict=True):
            assert after[0] == before[0]  # same trade rows, same order
            assert after[2] <= before[2]  # quantity NEVER grows back
            if before[1] == "closed":
                assert after[1] == "closed"  # a close is never undone
                assert after == before  # ... and never re-priced
            if before[4] is not None:
                assert after[4] is not None and after[4] >= before[4]  # stops only tighten
        if current == previous:
            fixed_point = True
            break
        previous = current
    assert fixed_point, "management kept acting forever on unchanged data"


class StaleProvider(StubProvider):
    """Bars whose newest timestamp is a month old — stale by any threshold."""

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        frame = super().get_bars(symbol, *a, **k)
        frame = frame.copy()
        frame.index = frame.index - pd.Timedelta(days=30)
        return frame


def test_stale_data_never_feeds_decisions(factory: sessionmaker[Session], user_dir: Path) -> None:
    """A stale scan generates NO conviction and autopilot takes NOTHING."""
    _enable_autopilot(user_dir)
    result = _scan(factory, StaleProvider())
    assert result["stale"] is True
    assert result["autopilot_entries"] == 0
    with factory() as session:
        assert session.query(ConvictionScore).count() == 0
        assert session.query(Trade).filter_by(status="open").count() == 0


def test_every_automated_entry_has_a_stop_below_entry(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    _enable_autopilot(user_dir)
    result = _scan(factory)
    assert result["autopilot_entries"] >= 1
    with factory() as session:
        for trade in session.query(Trade).filter_by(status="open").all():
            assert trade.quantity > 0
            assert trade.initial_stop is not None and trade.initial_stop > 0
            assert trade.initial_stop < trade.entry_price  # a stop above entry is nonsense


# --------------------------------------------------------------------------- #
# buying power / sizing / fills
# --------------------------------------------------------------------------- #
def test_order_beyond_buying_power_rejected_and_cash_untouched(
    factory: sessionmaker[Session],
) -> None:
    broker = PaperBrokerage(factory, clock=lambda: WEDNESDAY)
    starting = broker.get_account().cash
    broker.place_order(_ticket("whale", quantity=1_000_000))
    quote = Quote(symbol="AAPL", ts=WEDNESDAY, bid=499.9, ask=500.1, last=500.0, volume=1e9)
    broker.process_tick({"AAPL": quote}, ts=WEDNESDAY)

    order = broker.get_order("whale")
    assert order.status.value == "cancelled"  # pulled loudly, never filled
    cancel_events = [e for e in order.events if e["to_status"] == "cancelled"]
    assert cancel_events and "buying power" in str(cancel_events[-1]["reason"])
    account = broker.get_account()
    assert account.cash == pytest.approx(starting)
    assert account.buying_power >= 0.0
    assert broker.get_positions() == []


def test_buying_power_never_negative_under_stress(
    factory: sessionmaker[Session],
) -> None:
    """300 seeded random operations: buying power and settled cash can never
    go negative, and no position quantity can ever be negative."""
    broker = PaperBrokerage(factory, clock=lambda: WEDNESDAY)
    rng = np.random.default_rng(11)
    price = 250.0
    for i in range(300):
        price = max(price * float(1 + rng.normal(0, 0.02)), 1.0)
        ts = WEDNESDAY + dt.timedelta(minutes=i)
        action = int(rng.integers(0, 3))
        if action == 0:
            broker.place_order(_ticket(f"s{i}", quantity=int(rng.integers(1, 400))), ts=ts)
        elif action == 1:
            try:
                broker.close_position("primary", "AAPL", ts=ts)
            except Exception:  # noqa: BLE001 — nothing held is a legal no-op
                pass
        quote = Quote(
            symbol="AAPL", ts=ts, bid=price - 0.05, ask=price + 0.05, last=price, volume=2e6
        )
        broker.process_tick({"AAPL": quote}, ts=ts)

        account = broker.get_account()
        assert account.buying_power >= 0.0
        for position in broker.get_positions(include_closed=True):
            assert position.quantity >= 0


def test_impossible_fills_cannot_happen() -> None:
    """400 seeded random executions: a buy can never fill below the ask, a
    sell never above the bid, a limit is never violated, quantity never
    exceeds the request, and fees/prices are never negative."""
    from momentum.brokerage.config import RealismLevel, default_config

    rng = np.random.default_rng(23)
    for realism in (RealismLevel.REALISTIC, RealismLevel.PESSIMISTIC):
        cfg = default_config().execution.model_copy(update={"realism": realism})
        sim = ExecutionSimulator(cfg)
        for i in range(200):
            mid = float(rng.uniform(2, 800))
            half = float(rng.uniform(0.005, 0.02)) * mid / 2
            quote = Quote(
                symbol="X",
                ts=WEDNESDAY + dt.timedelta(minutes=int(rng.integers(0, 390))),
                bid=mid - half,
                ask=mid + half,
                last=mid,
                volume=float(rng.uniform(1e3, 1e7)),
            )
            side = Side.LONG if rng.integers(0, 2) == 0 else Side.SHORT
            requested = int(rng.integers(1, 5_000))
            limit = None
            if rng.integers(0, 2) == 0:
                limit = quote.ask * 1.001 if side is Side.LONG else quote.bid * 0.999
            execution = sim.execute(side=side, quantity=requested, quote=quote, limit_price=limit)

            assert 0 < execution.quantity <= requested
            assert execution.price > 0 and execution.fees >= 0
            if limit is not None:
                if side is Side.LONG:
                    assert execution.price <= limit + 1e-9
                else:
                    assert execution.price >= limit - 1e-9
            else:
                if side is Side.LONG:
                    assert execution.price >= quote.ask - 1e-9  # never inside the spread
                else:
                    assert execution.price <= quote.bid + 1e-9


def test_trailing_stop_never_loosens() -> None:
    """A 500-step random walk can only ever RAISE an exit trail trigger."""
    from momentum.brokerage.oms import BrokerOrder

    order = BrokerOrder(
        order_id="trail",
        account_id="primary",
        symbol="AAPL",
        side=Side.SHORT,  # selling to exit a long
        quantity=100,
        order_type=OrderType.TRAILING_STOP,
        time_in_force=TimeInForce.GTC,
        created_ts=WEDNESDAY,
        trail_percent=5.0,
    )
    rng = np.random.default_rng(31)
    price, last_trigger = 100.0, 0.0
    for _ in range(500):
        price = max(price * float(1 + rng.normal(0, 0.02)), 1.0)
        order.ratchet_trail(price)
        trigger = order.trail_trigger
        assert trigger is not None
        assert trigger >= last_trigger - 1e-12  # ratchets up, never down
        last_trigger = trigger


# --------------------------------------------------------------------------- #
# infinite loops / scheduler drift / orphaned workers / memory
# --------------------------------------------------------------------------- #
def test_gap_math_and_backoff_can_never_spin_forever() -> None:
    started = time.perf_counter()
    missed = automation_state.missed_scans_between(
        WEDNESDAY - dt.timedelta(days=3650), WEDNESDAY, interval_seconds=60
    )
    assert time.perf_counter() - started < 5.0  # the 14-day cap bounds the walk
    assert 0 < missed <= 14 * 24 * 60

    daemon = MarketDaemon(lambda s, m: {}, config=DaemonConfig())
    daemon._consecutive_failures = 40  # a long provider outage
    delay = daemon._delay_after(MarketState.REGULAR)
    assert delay == daemon.config.backoff_max_seconds  # capped — never explodes
    assert delay > 0  # and never a zero-delay busy loop


def test_scheduler_delays_are_always_positive_and_bounded() -> None:
    daemon = MarketDaemon(lambda s, m: {}, config=DaemonConfig())
    for failures in range(0, 30):
        daemon._consecutive_failures = failures
        for state in MarketState:
            delay = daemon._delay_after(state)
            assert (
                0
                < delay
                <= max(daemon.config.backoff_max_seconds, daemon.config.closed_interval_seconds)
            )


def test_no_orphaned_workers_after_stop() -> None:
    open_hours = dt.datetime(2026, 7, 1, 12, 0, tzinfo=ET).astimezone(dt.UTC)
    config = DaemonConfig(scan_interval_seconds=0.01, closed_interval_seconds=0.02)
    baseline = threading.active_count()
    for _ in range(5):
        daemon = MarketDaemon(lambda s, m: {"ok": True}, config=config, clock=lambda: open_hours)
        daemon.start()
        daemon.stop(timeout=5.0)
        assert not daemon.running
        thread = daemon._thread
        assert thread is not None and not thread.is_alive()
    assert threading.active_count() <= baseline  # nothing left running


def test_soak_event_buffer_and_memory_stay_bounded() -> None:
    """20k published events + 2k cycles: the buffer stays at its cap and the
    second half allocates no meaningful additional memory (no leak)."""
    daemon = MarketDaemon(lambda s, m: {"n": 1}, config=DaemonConfig())
    for i in range(10_000):
        daemon._publish("scan", f"warmup {i}")
    for _ in range(1_000):
        daemon._run_cycle(MarketState.REGULAR, False)

    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    for i in range(10_000):
        daemon._publish("scan", f"steady-state {i}")
    for _ in range(1_000):
        daemon._run_cycle(MarketState.REGULAR, False)
    after, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(daemon.events(10**9)) <= daemon.config.event_buffer
    assert after - before < 1_000_000  # < 1MB drift across 11k more operations


# --------------------------------------------------------------------------- #
# double-click takes
# --------------------------------------------------------------------------- #
def test_double_take_is_refused(factory: sessionmaker[Session], user_dir: Path) -> None:
    from momentum.api import trade_lifecycle_service

    scan = _scan(factory)
    assert scan["candidates"] >= 1
    with factory() as session:
        first = trade_lifecycle_service.take_trade(session, "AAA", ts=WEDNESDAY)
        assert first["ok"] is True, first.get("error")
    with factory() as session:
        second = trade_lifecycle_service.take_trade(session, "AAA", ts=WEDNESDAY)
        assert second["ok"] is False
        assert "already has an open paper trade" in second["error"]
    with factory() as session:
        assert session.query(Trade).filter_by(symbol="AAA", status="open").count() == 1
