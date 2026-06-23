"""Tests for the /universes endpoints + scan-at-scale over large universes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.api.app import create_app
from momentum.api.jobs import JobManager
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ConvictionScore, ScanResult
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner


@pytest.fixture(autouse=True)
def _isolated_user_dir(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _bars(start: float = 50.0, n: int = 260, seed: int = 0) -> pd.DataFrame:
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
    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        return _bars(seed=hash(symbol) % 9973)


def _client(factory: sessionmaker[Session]) -> TestClient:
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    app.state.provider_factory = lambda: StubProvider()
    return TestClient(app)


# --------------------------------------------------------------------------- #
# REST surface
# --------------------------------------------------------------------------- #
def test_list_select_create_import_sector_delete(factory: sessionmaker[Session]) -> None:
    client = _client(factory)

    listing = client.get("/universes").json()
    assert listing["selected"] == "default"
    assert {u["key"] for u in listing["universes"]} >= {"sp500", "nasdaq100", "russell3000"}

    # select a built-in
    assert client.put("/universes/selected", json={"key": "nasdaq100"}).json()["selected"] == (
        "nasdaq100"
    )
    sel = client.get("/universes/selected").json()
    assert sel["key"] == "nasdaq100" and sel["size"] == 100

    # create custom
    created = client.post("/universes", json={"label": "Picks", "symbols": ["AAPL", "MSFT"]})
    assert created.status_code == 201
    key = created.json()["key"]

    # import
    imported = client.post("/universes/import", json={"label": "Imp", "text": "NVDA TSLA"})
    assert imported.status_code == 201 and imported.json()["size"] == 2

    # sector
    sector = client.post("/universes/sector", json={"sector": "Energy", "base": "default"})
    assert sector.status_code == 201 and sector.json()["kind"] == "sector"

    # delete the custom one
    assert client.delete(f"/universes/{key}").json()["deleted"] is True
    assert client.delete(f"/universes/{key}").status_code == 404


def test_select_unknown_is_400(factory: sessionmaker[Session]) -> None:
    client = _client(factory)
    assert client.put("/universes/selected", json={"key": "nope"}).status_code == 400


def test_delete_builtin_is_400(factory: sessionmaker[Session]) -> None:
    client = _client(factory)
    assert client.delete("/universes/sp500").status_code == 400


def test_scan_uses_selected_universe(factory: sessionmaker[Session]) -> None:
    """End to end: selecting a universe makes Run Scan process exactly that set."""
    client = _client(factory)
    # A small custom universe so the assertion is exact.
    created = client.post(
        "/universes", json={"label": "Three", "symbols": ["AAA", "BBB", "CCC"]}
    ).json()
    client.put("/universes/selected", json={"key": created["key"]})

    job = client.post("/actions/scan", json={"lookback_days": 400}).json()
    assert job["status"] == "succeeded"
    result = job["result"]
    assert result["universe_size"] == 3
    assert result["universe_key"] == created["key"]
    assert result["symbols_scanned"] == 3
    assert "duration_ms" in result and "symbols_passed" in result


# --------------------------------------------------------------------------- #
# Scale: the scanner/pipeline must process large universes
# --------------------------------------------------------------------------- #
def _relaxed_scanner() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


def _synthetic_universe(n: int) -> dict[str, pd.DataFrame]:
    return {f"SYM{i:04d}": _bars(seed=i) for i in range(n)}


@pytest.mark.parametrize("n", [500, 1000])
def test_scanner_processes_large_universe(n: int) -> None:
    bars = _synthetic_universe(n)
    result = _relaxed_scanner().scan(bars)
    # Every symbol with enough history is featurised; the result is ranked.
    assert len(result.features) == n
    assert len(result.candidates) >= 1
    ranks = [c.rank for c in result.candidates]
    assert ranks == sorted(ranks)  # rank order is monotonic


@pytest.mark.slow
def test_scanner_processes_3000_symbol_universe() -> None:
    bars = _synthetic_universe(3000)
    result = _relaxed_scanner().scan(bars)
    assert len(result.features) == 3000
    assert len(result.candidates) >= 1


def test_run_scan_at_scale_persists(factory: sessionmaker[Session]) -> None:
    """run_scan over a 600-symbol universe persists scan + conviction and reports stats."""
    symbols = [f"SYM{i:04d}" for i in range(600)]

    def _noop(_p: float, _m: str) -> None:
        return None

    result = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed_scanner(),
        symbols=symbols,
        lookback_days=400,
        progress=_noop,
        universe_key="big",
        universe_label="Big",
    )
    assert result["universe_size"] == 600
    assert result["symbols_scanned"] == 600
    assert result["symbols_passed"] == result["candidates"] >= 1
    with factory() as session:
        assert session.query(ScanResult).count() == result["candidates"]
        assert session.query(ConvictionScore).count() == result["candidates"]
