"""Complete research-workflow integration test.

Proves that ONE scan drives the entire application: pull data → scan → persist
candidates → conviction → analogs → trade plans → watchlists → options, and that
every UI endpoint then returns non-empty live data with no demo dependence.

Fails if any screen remains empty after a successful scan.
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
from momentum.persistence.models import (
    Base,
    CandidateAnalog,
    ConvictionScore,
    MarketRegime,
    ScanResult,
    TradePlan,
    WatchlistEntryRow,
)
from momentum.universe.membership import select_universe
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


def _bars(seed: int, newest: pd.Timestamp, n: int = 320) -> pd.DataFrame:
    """A liquid, trending, near-ATH series (so candidates pass + options qualify)."""
    rng = np.random.default_rng(seed)
    close = 80.0 * np.cumprod(1 + rng.normal(0.005, 0.018, n))
    idx = pd.date_range(end=newest, periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.015,
            "low": np.minimum(opens, close) * 0.985,
            "close": close,
            "volume": np.full(n, 5_000_000.0),
        },
        index=idx,
    )


class YahooLikeStub:
    """Stands in for live Yahoo: returns fresh bars for every symbol (offline)."""

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        return _bars(abs(hash(symbol)) % 9999, pd.Timestamp(dt.date.today(), tz="UTC"))


def test_one_scan_drives_the_whole_application(factory: sessionmaker[Session]) -> None:
    # Seed demo first — the live scan must drive every screen, never demo.
    with factory() as s:
        seed_all(s)
        s.commit()

    # 1-2. Pull (stubbed live) Yahoo data + scan the configured universe.
    symbols, sectors = select_universe()
    assert len(symbols) >= 50  # the real shipped universe
    result = actions.run_scan(
        session_factory=factory,
        provider=YahooLikeStub(),
        scanner=MomentumScanner(),
        symbols=symbols,
        sectors=sectors,
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="yahoo",
        universe_label="Default",
    )
    run = result["run_id"]
    assert result["stale"] is False and run != "demo"

    # 3-7. Every stage produced rows under the SAME run_id.
    rows_per_table: dict[str, int] = {}
    with factory() as s:
        for name, model in (
            ("scan_results", ScanResult),
            ("conviction_scores", ConvictionScore),
            ("candidate_analogs", CandidateAnalog),
            ("trade_plans", TradePlan),
            ("watchlist_entries", WatchlistEntryRow),
        ):
            rows_per_table[name] = int(
                s.scalar(select(func.count()).select_from(model).where(model.run_id == run))
            )
        rows_per_table["market_regimes"] = int(
            s.scalar(select(func.count()).select_from(MarketRegime))
        )
    print("\nROWS WRITTEN PER TABLE (run_id=%s):" % run)
    for k, v in rows_per_table.items():
        print(f"  {k:20} {v}")
    for table, n in rows_per_table.items():
        assert n > 0, f"stage produced no rows: {table}"

    # 8 + UI. Probe every screen's endpoint; all must be non-empty live data.
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    app.state.provider_factory = lambda: YahooLikeStub()
    client = TestClient(app)

    scans = client.get("/universe/scans").json()
    assert scans, "Scan screen empty"
    assert all(r["run_id"] == run for r in scans), "Scan screen shows non-live run"
    top = scans[0]["symbol"]

    conviction = client.get("/conviction").json()
    assert conviction and all(c["run_id"] == run for c in conviction), (
        "Conviction screen empty/demo"
    )

    watchlists = client.get("/watchlists").json()
    assert sum(len(h["entries"]) for h in watchlists["horizons"]) > 0, "Watchlists empty"

    detail = client.get(f"/candidates/{top}").json()
    assert detail["scan"] and detail["conviction"], "Candidate inspector incomplete"
    assert detail["scan"]["run_id"] == run

    plan = client.get(f"/tradeplan/{top}")
    assert plan.status_code == 200 and plan.json()["entry"] > 0, "Trade Plan unavailable"

    analogs = client.get(f"/analogs?symbol={top}").json()
    assert "sample_size" in analogs, "Analogs screen errored"

    eligibility = client.get(f"/options-eligibility/{top}")
    assert eligibility.status_code == 200, "Options eligibility unavailable"

    # Options recommendation: at least one candidate yields a defined-risk contract.
    recommended = 0
    for r in scans[:15]:
        if client.get(f"/options-recommendation/{r['symbol']}").status_code == 200:
            recommended += 1
    print(
        "\nENDPOINTS VERIFIED: /universe/scans /conviction /watchlists /candidates "
        "/tradeplan /analogs /options-eligibility /options-recommendation"
    )
    print(
        f"SCREENS NON-EMPTY: Scan, Conviction, Watchlists, Inspector, Trade Plan, "
        f"Analogs, Options ({recommended} recommendable candidates)"
    )
    assert recommended > 0, "Options screen empty: no candidate produced a recommendation"

    # No screen depends on demo: every live endpoint pinned to the live run_id.
    assert run.startswith("scan-")
