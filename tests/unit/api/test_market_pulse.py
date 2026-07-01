"""Market pulse end-to-end: every scan snapshots itself, diffs against the
previous scan, emits deduplicated alerts + activities, records performance —
and the daemon cycle skips the pipeline entirely when nothing changed."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.persistence.models import (
    Activity,
    Alert,
    Base,
    ScanDelta,
    ScanSnapshot,
    ScanStat,
)
from momentum.persistence.repositories.pulse import ScanSnapshotRepository
from momentum.universe.screener import MomentumScanner

SYMBOLS = [f"SYM{i:03d}" for i in range(12)]


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


def _bars(seed: int, newest: pd.Timestamp, *, bump: float = 0.0, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.02, n)) * (1 + bump)
    idx = pd.date_range(end=newest, periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.02,
            "low": np.minimum(opens, close) * 0.98,
            "close": close,
            "volume": np.full(n, 3_000_000.0),
        },
        index=idx,
    )


class StubProvider:
    name = "stub"

    def __init__(self) -> None:
        self.bump = 0.0

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        newest = pd.Timestamp(dt.date.today(), tz="UTC")
        return _bars(abs(hash(symbol)) % 9999, newest, bump=self.bump)


def _scan(factory: sessionmaker[Session], provider: StubProvider) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=provider,
        scanner=MomentumScanner(),
        symbols=SYMBOLS,
        sectors={s: "Technology" for s in SYMBOLS},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Default",
        market_state="regular",
    )


def _count(factory: sessionmaker[Session], model: Any) -> int:
    with factory() as s:
        return int(s.scalar(select(func.count()).select_from(model)) or 0)


# --------------------------------------------------------------------------- #
# snapshots + deltas + alerts + activities + stats via run_scan
# --------------------------------------------------------------------------- #
def test_every_scan_snapshots_and_records_stats(factory: sessionmaker[Session]) -> None:
    provider = StubProvider()
    first = _scan(factory, provider)
    assert first["snapshot_persisted"] == 1
    assert first["deltas_generated"] == 0  # nothing to diff against yet
    assert _count(factory, ScanSnapshot) == 1
    assert _count(factory, ScanStat) == 1

    with factory() as s:
        stat = s.scalars(select(ScanStat)).one()
        assert stat.duration_ms > 0
        assert stat.symbols_processed > 0
        assert stat.db_writes > 0
        assert stat.convictions_generated == first["conviction_scores_persisted"]
        assert stat.memory_mb is not None and stat.memory_mb > 0
        snapshot = s.scalars(select(ScanSnapshot)).one()
        assert snapshot.market_state == "regular"
        assert snapshot.payload["candidates"]
        assert snapshot.payload["regime"]["regime"] is not None


def test_second_scan_generates_deltas_alerts_activities(
    factory: sessionmaker[Session],
) -> None:
    provider = StubProvider()
    _scan(factory, provider)
    provider.bump = 0.08  # +8% across the board → conviction/price/watchlist churn
    second = _scan(factory, provider)

    assert second["deltas_generated"] > 0
    assert _count(factory, ScanDelta) == second["deltas_generated"]
    assert _count(factory, Activity) == second["activities_generated"]
    with factory() as s:
        deltas = list(s.scalars(select(ScanDelta)))
        assert all(d.direction in ("UPGRADE", "DOWNGRADE") for d in deltas)
        price_deltas = [d for d in deltas if d.metric == "price"]
        assert price_deltas and all(d.previous_value is not None for d in price_deltas)
        assert all(d.reason for d in deltas)


def test_identical_rescan_emits_nothing_new(factory: sessionmaker[Session]) -> None:
    provider = StubProvider()
    _scan(factory, provider)
    second = _scan(factory, provider)  # identical data
    assert second["deltas_generated"] == 0
    assert second["alerts_generated"] == 0
    assert _count(factory, ScanSnapshot) == 2  # snapshots still recorded (immutable log)


def test_alerts_never_duplicate(factory: sessionmaker[Session]) -> None:
    provider = StubProvider()
    _scan(factory, provider)
    provider.bump = 0.15
    second = _scan(factory, provider)
    alerts_after_change = _count(factory, Alert)
    assert alerts_after_change == second["alerts_generated"]

    third = _scan(factory, provider)  # same data again — same transitions, no new alerts
    assert third["alerts_generated"] == 0
    assert _count(factory, Alert) == alerts_after_change


def test_snapshots_are_immutable(factory: sessionmaker[Session]) -> None:
    provider = StubProvider()
    _scan(factory, provider)
    with factory() as s:
        repo = ScanSnapshotRepository(s)
        row = repo.latest()
        assert row is not None
        with pytest.raises(NotImplementedError):
            repo.delete(row)


def test_pulse_routes(factory: sessionmaker[Session]) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app
    from momentum.api.jobs import JobManager

    provider = StubProvider()
    _scan(factory, provider)
    provider.bump = 0.1
    _scan(factory, provider)

    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)

    timeline = client.get("/timeline").json()
    assert len(timeline) == 2

    replay = client.get(f"/timeline/{timeline[0]['id']}").json()
    assert replay["payload"]["candidates"]

    diff = client.get(f"/timeline/diff?a={timeline[1]['id']}&b={timeline[0]['id']}").json()
    assert diff and all(d["direction"] in ("UPGRADE", "DOWNGRADE") for d in diff)

    deltas = client.get("/deltas?metric=price&limit=5").json()
    assert deltas and all(d["metric"] == "price" for d in deltas)

    assert client.get("/alerts").status_code == 200
    assert client.get("/activity").status_code == 200
    stats = client.get("/scan-stats").json()
    assert len(stats) == 2
    summary = client.get("/scan-stats/summary").json()
    assert summary["scans_recorded"] == 2

    assert client.get("/timeline/diff?a=1&b=999").status_code == 404


# --------------------------------------------------------------------------- #
# daemon cycle: incremental skip + metrics
# --------------------------------------------------------------------------- #
def test_daemon_cycle_skips_pipeline_when_nothing_changed(
    factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    from momentum.api import daemon_service, universe_service
    from momentum.daemon import DaemonConfig, MarketState

    provider = StubProvider()
    monkeypatch.setattr(
        universe_service,
        "resolve_selected",
        lambda session: SimpleNamespace(
            symbols=tuple(SYMBOLS),
            sectors={s: "Technology" for s in SYMBOLS},
            key="default",
            label="Default",
        ),
    )
    cfg = DaemonConfig(bar_reuse_seconds=300.0)
    cycle, cache = daemon_service.build_cycle(factory, lambda: provider, config=cfg)

    first = cycle(MarketState.REGULAR, False)
    assert first["skipped_pipeline"] is False
    assert first["symbols_recomputed"] > 0
    assert cache.size() > 0

    second = cycle(MarketState.REGULAR, False)  # nothing changed within reuse window
    assert second["skipped_pipeline"] is True
    assert second["symbols_recomputed"] == 0
    assert second["symbols_skipped"] > 0
    assert second["cache_hit_rate"] == 1.0
    assert _count(factory, ScanSnapshot) == 1  # prior results reused, not rebuilt

    manual = cycle(MarketState.CLOSED, True)  # manual scan always runs fully
    assert manual["skipped_pipeline"] is False
    assert _count(factory, ScanSnapshot) == 2
