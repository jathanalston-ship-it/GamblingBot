"""Tests for the /actions endpoints (offline: sync job runner + stub provider)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from momentum.api.app import create_app
from momentum.api.jobs import JobManager
from momentum.persistence.models import AuditLog, Run, Trade


def _bars(start: float = 50.0, n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(0.004, 0.015, n))
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.01,
            "low": np.minimum(opens, close) * 0.99,
            "close": close,
            "volume": np.full(n, 2_000_000.0),
        },
        index=idx,
    )
    frame.index.name = "timestamp"
    return frame


class StubProvider:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        return pd.DataFrame() if self.empty else _bars(seed=hash(symbol) % 100)


def _client(session_factory: sessionmaker, *, provider: StubProvider | None = None) -> TestClient:
    app = create_app(session_factory=session_factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())  # synchronous → terminal jobs
    app.state.provider_factory = lambda: provider or StubProvider()
    return TestClient(app)


def test_scan_action_runs_and_completes(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    resp = client.post("/actions/scan", json={"symbols": ["AAA", "BBB"], "lookback_days": 400})
    assert resp.status_code == 202
    job = resp.json()
    assert job["kind"] == "scan"
    # The synchronous runner means the job is already terminal.
    assert job["status"] == "succeeded"
    assert job["result"]["run_id"].startswith("scan-")
    # Pollable by id.
    polled = client.get(f"/actions/jobs/{job['id']}").json()
    assert polled["status"] == "succeeded"


def test_backtest_action(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    job = client.post("/actions/backtest", json={"symbols": ["AAA"], "lookback_days": 600}).json()
    assert job["status"] == "succeeded"
    assert "final_equity" in job["result"]
    assert job["result"]["persisted"] is True
    # The persisted run shows up on the Backtesting screen's endpoint.
    opts = client.get("/backtests/optimizations").json()
    assert any(o["run_id"] == job["result"]["run_id"] for o in opts)


def test_seed_demo_action(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    job = client.post("/actions/seed-demo").json()
    assert job["status"] == "succeeded"
    assert job["result"]["seeded"] is True
    # Demo data now lights up the previously-empty screens.
    assert len(client.get("/universe/scans").json()) > 0
    assert len(client.get("/portfolio/snapshots").json()) > 0
    assert len(client.get("/backtests/optimizations").json()) > 0
    assert len(client.get("/trades?status=closed&run_id=demo").json()) == 50


def test_paper_session_action(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    job = client.post("/actions/paper-session", json={"symbols": ["AAA", "BBB"]}).json()
    assert job["status"] == "succeeded"
    assert "run_id" in job["result"]


def test_refresh_data_action(
    session_factory: sessionmaker, tmp_path: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path))
    client = _client(session_factory)
    job = client.post("/actions/refresh-data", json={"symbols": ["AAA", "BBB"]}).json()
    assert job["status"] == "succeeded"
    assert job["result"]["fetched"] == 2


def test_scan_action_fails_without_data(session_factory: sessionmaker) -> None:
    client = _client(session_factory, provider=StubProvider(empty=True))
    job = client.post("/actions/scan", json={"symbols": ["AAA"]}).json()
    assert job["status"] == "failed"
    assert "no market data" in job["error"]


def test_job_not_found(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    assert client.get("/actions/jobs/does-not-exist").status_code == 404


def test_jobs_list(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    client.post("/actions/backtest", json={"symbols": ["AAA"]})
    listing = client.get("/actions/jobs").json()
    assert len(listing) >= 1
    assert listing[0]["kind"] == "backtest"


def test_replay_action(session_factory: sessionmaker) -> None:
    # Seed a run + trade + audit, then replay it.
    with session_factory() as s:
        s.add(
            Run(
                run_id="demo",
                mode="paper",
                as_of=dt.date(2026, 1, 5),
                status="completed",
                started_at=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
            )
        )
        s.add(
            Trade(
                run_id="demo",
                symbol="AAPL",
                direction="long",
                status="closed",
                entry_ts=dt.datetime(2026, 1, 5, 15, tzinfo=dt.UTC),
                entry_price=50.0,
                exit_price=60.0,
                quantity=100,
                net_pnl=998.0,
            )
        )
        s.add(
            AuditLog(
                event_type="position_opened",
                ts=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
                run_id="demo",
                symbol="AAPL",
                summary="opened",
            )
        )
        s.commit()

    client = _client(session_factory)
    body = client.post("/actions/replay", json={"run_id": "demo"}).json()
    assert body["run"]["run_id"] == "demo"
    assert len(body["closed_trades"]) == 1
    assert client.post("/actions/replay", json={"run_id": "nope"}).status_code == 404
