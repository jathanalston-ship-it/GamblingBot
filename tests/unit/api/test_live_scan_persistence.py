"""Live Scan Persistence — Run Scan must drive every read screen off ONE live
run_id, with demo never surfacing once live data exists.

Reproduces the audited failure (demo dated *today* outranking a live scan dated at
the newest *bar* date = yesterday) and proves it is fixed: with demo seeded, a live
scan's scan_results / conviction / regime / watchlists all share the live run_id and
every endpoint returns that run, not demo.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.api.app import create_app
from momentum.api.jobs import JobManager
from momentum.demo import seed_all
from momentum.persistence.models import Base, ConvictionScore, ScanResult, WatchlistEntryRow
from momentum.universe.screener import MomentumScanner


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


def _bars(seed: int, newest: pd.Timestamp, n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(0.005, 0.02, n))
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
    """Fresh bars whose newest bar is `newest` for every symbol (offline)."""

    def __init__(self, newest: pd.Timestamp) -> None:
        self.newest = newest

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        return _bars(abs(hash(symbol)) % 9999, self.newest)


def _counts(factory: sessionmaker[Session]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    with factory() as s:
        for name, col in (
            ("scan_results", ScanResult.run_id),
            ("conviction_scores", ConvictionScore.run_id),
            ("watchlist_entries", WatchlistEntryRow.run_id),
        ):
            rows = s.execute(select(col, func.count()).group_by(col)).all()
            out[name] = {str(rid): n for rid, n in rows}
    return out


def _run_live_scan(factory: sessionmaker[Session], days_old: int) -> dict[str, Any]:
    symbols = [f"SYM{i:03d}" for i in range(40)]
    newest = pd.Timestamp(dt.date.today() - dt.timedelta(days=days_old), tz="UTC")
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(newest),
        scanner=MomentumScanner(),
        symbols=symbols,
        sectors={s: "Technology" for s in symbols},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Default",
    )


def test_run_scan_persists_live_and_drives_all_reads(factory: sessionmaker[Session]) -> None:
    # Demo first (the default app state). newest bar = YESTERDAY: the audited case
    # where demo's today-dated rows used to outrank the live scan.
    with factory() as s:
        seed_all(s)
        s.commit()

    before = _counts(factory)
    assert before["scan_results"] == {"demo": 15}
    assert before["conviction_scores"] == {"demo": 15}
    assert "demo" in before["watchlist_entries"]

    result = _run_live_scan(factory, days_old=1)
    live = result["run_id"]
    assert result["stale"] is False
    assert result["scan_results_persisted"] >= 1
    assert result["conviction_scores_persisted"] == result["scan_results_persisted"]
    assert result["watchlists_generated"] >= 1

    after = _counts(factory)
    # Exact row counts: demo rows untouched; live rows added under the live run_id.
    assert after["scan_results"]["demo"] == 15
    assert after["scan_results"][live] == result["scan_results_persisted"]
    assert after["conviction_scores"][live] == result["conviction_scores_persisted"]
    assert after["watchlist_entries"][live] == result["watchlists_generated"]

    # Every read endpoint returns the LIVE run, never demo — with demo present and
    # newer-dated. (This is the bug the audit reproduced.)
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)

    scans = client.get("/universe/scans").json()
    assert scans and all(r["run_id"] == live for r in scans)

    conv = client.get("/conviction").json()
    assert conv and all(c["run_id"] == live for c in conv)
    assert all(c.get("explanation") for c in conv)  # explanation persisted

    wls = client.get("/watchlists").json()
    total = sum(len(h["entries"]) for h in wls["horizons"])
    assert total == result["watchlists_generated"] >= 1

    # The Scan-inspector aggregate (/candidates) also resolves to the live run.
    top_symbol = scans[0]["symbol"]
    detail = client.get(f"/candidates/{top_symbol}").json()
    assert detail["scan"] is not None and detail["scan"]["run_id"] == live


def test_demo_never_used_when_live_conviction_exists(factory: sessionmaker[Session]) -> None:
    """Watchlists rank the live conviction batch, not the (newer-dated) demo seed."""
    with factory() as s:
        seed_all(s)
        s.commit()
    result = _run_live_scan(factory, days_old=1)

    from momentum.api import watchlist_service

    with factory() as s:
        cands, as_of, batch_run = watchlist_service._load_candidates(s, None)
    assert batch_run == result["run_id"]  # live wins over demo despite older date
    assert len(cands) == result["conviction_scores_persisted"]


def test_stale_scan_yields_empty_watchlists_not_demo(factory: sessionmaker[Session]) -> None:
    """A stale live scan persists scan rows but no conviction → watchlists empty
    (the honest 'No live conviction data available'), never a demo fallback."""
    with factory() as s:
        seed_all(s)
        s.commit()
    result = _run_live_scan(factory, days_old=10)
    assert result["stale"] is True
    assert result["conviction_scores_persisted"] == 0

    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)
    # Scan screen shows the live (stale) run, not demo.
    scans = client.get("/universe/scans").json()
    assert scans and all(r["run_id"] == result["run_id"] for r in scans)
    # Watchlists are empty — no demo fallback.
    wls = client.get("/watchlists").json()
    assert sum(len(h["entries"]) for h in wls["horizons"]) == 0
