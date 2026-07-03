"""Production-readiness break-attempts — every failure mode, executed.

Each test here tries to BREAK a subsystem the way production will:
network/provider failures, disk full, database corruption, torn writes
(power loss), duplicate scans, stale/garbage state files, clock drift,
closed markets and weekends. The invariant under attack is always the same:
**fail loudly, corrupt nothing, recover on the next cycle.**

(Restart recovery, DST transitions, capped daemon backoff and multi-launch
locks are proven elsewhere: tests/unit/api/test_automation.py,
tests/unit/core/test_time_audit.py, tests/unit/daemon/test_worker.py and the
Electron suites in desktop/scripts/.)
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, automation_state
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, Run, ScanResult
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner
from tests.unit.api.test_actions import StubProvider, _noop

WEDNESDAY = dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.UTC)


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


def _relaxed() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


# --------------------------------------------------------------------------- #
# network / Yahoo failures
# --------------------------------------------------------------------------- #
def test_total_provider_outage_fails_loudly_never_silently(
    factory: sessionmaker[Session],
) -> None:
    """Yahoo down for every symbol: the scan RAISES (provider-named), writes
    no phantom scan rows, and the very next scan with data succeeds."""
    with pytest.raises(RuntimeError, match="no market data"):
        actions.run_scan(
            session_factory=factory,
            provider=StubProvider(empty=True),
            scanner=_relaxed(),
            symbols=["AAA", "BBB"],
            lookback_days=400,
            progress=_noop,
        )
    with factory() as session:
        assert session.query(ScanResult).count() == 0  # nothing half-written
        runs = session.query(Run).all()
        assert all(r.status != "completed" for r in runs)  # no fake success

    recovered = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
    )
    assert recovered["candidates"] >= 1  # the outage left no lasting damage


def test_partial_provider_outage_scans_the_survivors(
    factory: sessionmaker[Session],
) -> None:
    """Half the universe erroring must not abort the other half."""
    result = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(fail={"BBB", "CCC"}),
        scanner=_relaxed(),
        symbols=["AAA", "BBB", "CCC", "DDD"],
        lookback_days=400,
        progress=_noop,
    )
    assert result["symbols_scanned"] == 2  # AAA + DDD survived
    assert result["candidates"] >= 1


class FlakyMidScanProvider(StubProvider):
    """Dies on the Nth request — an outage that begins mid-scan."""

    def __init__(self, *, die_after: int) -> None:
        super().__init__()
        self.calls = 0
        self.die_after = die_after

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        self.calls += 1
        if self.calls > self.die_after:
            raise ConnectionError("network dropped mid-scan")
        return super().get_bars(symbol, *a, **k)


def test_outage_beginning_mid_scan_is_survivable(factory: sessionmaker[Session]) -> None:
    result = actions.run_scan(
        session_factory=factory,
        provider=FlakyMidScanProvider(die_after=2),
        scanner=_relaxed(),
        symbols=["AAA", "BBB", "CCC", "DDD", "EEE"],
        lookback_days=400,
        progress=_noop,
    )
    # The two symbols pulled before the drop are scanned; the rest recorded
    # as fetch failures — and the run still completes rather than crashing.
    assert result["symbols_scanned"] == 2


# --------------------------------------------------------------------------- #
# disk full
# --------------------------------------------------------------------------- #
def test_disk_full_heartbeat_never_kills_the_loop(
    user_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(*a: Any, **k: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", full)
    # Must swallow (log-only): a full disk cannot be allowed to stop scanning.
    automation_state.record_heartbeat(ts=WEDNESDAY)
    automation_state.mark_clean_shutdown(ts=WEDNESDAY)


def test_disk_full_database_fails_loudly_and_recovers(tmp_path: Path) -> None:
    """SQLite hits a hard page cap mid-scan: the scan RAISES (no silent
    partial success) and, once space exists again, the next scan succeeds."""
    db = tmp_path / "full.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    current_pages = engine.raw_connection().execute("PRAGMA page_count").fetchone()[0]

    from sqlalchemy import event

    # Cap at EXACTLY the current size: any page allocation is "disk full".
    # 40 scanned symbols guarantee the scan tables outgrow their root pages,
    # so the allocation (and the failure) is deterministic.
    cap = {"pages": current_pages}
    symbols = [f"S{i:02d}A" for i in range(40)]

    @event.listens_for(engine, "connect")
    def _limit(dbapi_conn: Any, record: Any) -> None:
        dbapi_conn.execute(f"PRAGMA max_page_count = {cap['pages']}")

    engine.dispose()  # force reconnect so the PRAGMA applies

    with pytest.raises(Exception, match="disk is full|database or disk"):
        actions.run_scan(
            session_factory=factory,
            provider=StubProvider(),
            scanner=_relaxed(),
            symbols=symbols,
            lookback_days=400,
            progress=_noop,
        )

    cap["pages"] = 1_000_000  # "space freed"
    engine.dispose()
    recovered = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=symbols,
        lookback_days=400,
        progress=_noop,
    )
    assert recovered["candidates"] >= 1
    with factory() as session:
        run = session.query(Run).filter_by(run_id=recovered["run_id"]).one()
        assert run.status == "completed"


# --------------------------------------------------------------------------- #
# database corruption
# --------------------------------------------------------------------------- #
def test_corrupt_database_is_detected_not_trusted(tmp_path: Path) -> None:
    db = tmp_path / "corrupt.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()

    # Overwrite every page after page 1 with garbage (torn write / bad sector).
    # Page 1 (header + sqlite_master root) stays valid so the file still opens;
    # every table's data pages are destroyed, so any read MUST hit corruption —
    # deterministic regardless of how schema changes shift the page layout.
    raw = bytearray(db.read_bytes())
    page = 4096
    garbage = b"\xde\xad\xbe\xef" * (page // 4)
    for start in range(page, len(raw), page):
        raw[start : start + page] = garbage[: len(raw) - start]
    db.write_bytes(bytes(raw))

    from momentum.update.integrity import check_integrity

    report = check_integrity(Path.cwd(), f"sqlite:///{db}")
    assert not report.ok  # the updater's gate refuses a corrupt database

    # And querying it raises a DatabaseError — never silently wrong data.
    engine2 = create_engine(f"sqlite:///{db}", future=True)
    with pytest.raises(Exception, match="malformed|not a database|file is"):
        with engine2.connect() as conn:
            conn.execute(text("PRAGMA integrity_check")).scalar()
            for row in conn.execute(text("SELECT * FROM trades")):
                _ = row


def test_torn_state_file_after_power_loss_is_survivable(user_dir: Path) -> None:
    """Power loss mid-write leaves garbage JSON: startup must not crash and
    must treat the file as absent (plus: writes are atomic via os.replace)."""
    (user_dir / "automation_state.json").write_bytes(b'{"last_heartbeat": "2026-')
    assert automation_state.detect_recovery(now=WEDNESDAY) is None
    assert automation_state.last_recovery() is None
    # A fresh heartbeat repairs the file completely.
    automation_state.record_heartbeat(ts=WEDNESDAY)
    assert automation_state.snapshot()["last_heartbeat"] == WEDNESDAY.isoformat()
    assert not (user_dir / "automation_state.json.tmp").exists()  # atomic path cleaned


def test_garbage_settings_yaml_degrades_to_defaults(user_dir: Path) -> None:
    (user_dir / "settings.yaml").write_text("{{{{ not yaml ::::")
    from momentum.api import user_settings

    assert user_settings.read_provider() == "yfinance"
    assert user_settings.read_autopilot()["enabled"] is False
    assert user_settings.read_account_balance() == 100_000.0


# --------------------------------------------------------------------------- #
# duplicate scans (same data, repeated cycles)
# --------------------------------------------------------------------------- #
def test_ten_duplicate_scans_change_nothing(factory: sessionmaker[Session]) -> None:
    provider = StubProvider()
    first = actions.run_scan(
        session_factory=factory,
        provider=provider,
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
    )
    for _ in range(9):
        again = actions.run_scan(
            session_factory=factory,
            provider=provider,
            scanner=_relaxed(),
            symbols=["AAA", "BBB"],
            lookback_days=400,
            progress=_noop,
        )
        assert again["run_id"] == first["run_id"]
    with factory() as session:
        assert session.query(ScanResult).count() == first["candidates"]  # no growth


# --------------------------------------------------------------------------- #
# clock drift / market closed / weekends
# --------------------------------------------------------------------------- #
def test_weekend_and_closed_market_take_no_automated_action(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    """Autopilot enabled + a closed market: scans may run manually, but no
    entries are ever taken outside the allowed sessions."""
    import yaml

    (user_dir / "settings.yaml").write_text(
        yaml.safe_dump({"autopilot": {"enabled": True, "min_conviction_score": 0}})
    )
    result = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
        market_state="closed",
    )
    assert result["autopilot_entries"] == 0

    from momentum.daemon.market_state import market_state

    saturday = dt.datetime(2026, 7, 4, 15, 0, tzinfo=dt.UTC)
    assert market_state(saturday).value == "closed"
    assert not market_state(saturday).scanning  # the daemon never scans weekends


def test_extreme_clock_drift_is_flagged_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    from email.utils import format_datetime

    from momentum.api import automation_health_service as health

    def drifted_probe(url: str) -> tuple[int | None, str | None, float]:
        remote = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=2)
        return 200, format_datetime(remote), 40.0

    monkeypatch.setattr(health, "_probe", drifted_probe)
    report = health.check_all(daemon=None)
    clock = next(c for c in report["checks"] if c["name"] == "clock_sync")
    assert clock["status"] == "critical"
    assert report["overall"] == "critical"  # drifted clock blocks autopilot start


# --------------------------------------------------------------------------- #
# money invariants under stress
# --------------------------------------------------------------------------- #
def test_venue_cash_conservation_under_stress(factory: sessionmaker[Session]) -> None:
    """100 random venue operations: cash + realized P&L always reconcile —
    fills can never mint or destroy money."""
    import numpy as np

    from momentum.brokerage import PaperBrokerage, Quote
    from momentum.brokerage.types import OrderTicket
    from momentum.core.enums import Side

    now = WEDNESDAY
    broker = PaperBrokerage(factory, clock=lambda: now)
    rng = np.random.default_rng(7)
    price = 100.0
    for i in range(100):
        price = max(price * float(1 + rng.normal(0, 0.01)), 1.0)
        ts = now + dt.timedelta(minutes=i)
        quote = Quote(
            symbol="AAPL", ts=ts, bid=price - 0.05, ask=price + 0.05, last=price, volume=5e6
        )
        if i % 7 == 0:
            broker.place_order(
                OrderTicket(
                    client_order_id=f"b{i}",
                    account_id="primary",
                    symbol="AAPL",
                    side=Side.LONG,
                    quantity=int(rng.integers(10, 60)),
                ),
                ts=ts,
            )
        elif i % 11 == 0:
            try:
                broker.close_position("primary", "AAPL", ts=ts)
            except Exception:
                pass  # nothing held — a legal no-op
        broker.process_tick({"AAPL": quote}, ts=ts)

    account = broker.get_account()
    positions = broker.get_positions(include_closed=True)
    realized = sum(p.realized_pnl for p in positions)
    open_cost = sum(p.avg_cost * p.quantity * p.multiplier for p in positions if p.is_open)
    fees = sum(f.fees for f in broker.get_fills(limit=500))
    # cash = starting - open cost basis + realized (fees already inside realized
    # for closes; entry fees reduce cash directly).
    assert account.cash == pytest.approx(
        account.starting_cash - open_cost + realized - _entry_fees(broker), abs=1.0
    )
    assert fees >= 0.0


def _entry_fees(broker: Any) -> float:
    return sum(f.fees for f in broker.get_fills(limit=500) if f.side.value == "long")
