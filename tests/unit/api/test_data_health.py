"""Tests for the Data Health Dashboard service + routes."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import data_health_service as dh
from momentum.api.app import create_app
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ConvictionScore, ScanMetadata, WatchlistEntryRow


@pytest.fixture(autouse=True)
def _isolated_user_dir(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


# --- pure status logic ------------------------------------------------------


def test_worst_picks_most_severe() -> None:
    assert dh._worst(["green", "yellow", "red"]) == "red"
    assert dh._worst(["green", "yellow"]) == "yellow"
    assert dh._worst(["green"]) == "green"
    assert dh._worst([]) == "yellow"


def test_age_status_thresholds() -> None:
    assert dh._age_status(10) == "green"
    assert dh._age_status(dh.FRESH_MINUTES + 1) == "yellow"
    assert dh._age_status(dh.STALE_MINUTES + 1) == "red"
    assert dh._age_status(None) == "red"


def test_humanize_age() -> None:
    assert dh._humanize_age(None) == "unknown"
    assert dh._humanize_age(30) == "30 min"
    assert dh._humanize_age(90).endswith("h")
    assert dh._humanize_age(3 * 24 * 60).endswith("d")


# --- aggregation ------------------------------------------------------------


def _seed_fresh(session: Session, now: dt.datetime) -> None:
    session.add(
        ScanMetadata(
            scan_id="scan-20260623",
            provider="yfinance",
            universe="S&P 500",
            bar_timestamp=now - dt.timedelta(hours=2),
            pull_timestamp=now - dt.timedelta(hours=1),
            symbol_count=480,
            data_age_minutes=120.0,
            stale=False,
        )
    )
    session.add(
        ConvictionScore(
            run_id="scan-20260623",
            symbol="NVDA",
            as_of=now.date(),
            ts=now - dt.timedelta(hours=1),
            score=87.0,
            band="EXTREME",
            model_version="v1",
            explanation="NVDA ranks highly (87/100) due to strong momentum.",
        )
    )
    session.add(
        WatchlistEntryRow(
            run_id="scan-20260623",
            as_of=now.date(),
            horizon="today",
            horizon_label="Today",
            rank=1,
            symbol="NVDA",
            conviction=87.0,
            base_conviction=87.0,
            risk_rating="Medium",
            horizon_days=1,
        )
    )
    session.commit()


def test_empty_db_reports_no_live_conviction(factory: sessionmaker[Session]) -> None:
    now = dt.datetime(2026, 6, 23, 12, tzinfo=dt.UTC)
    with factory() as session:
        result = dh.data_health(session, provider_name="yfinance", now=now)
    metrics = {m["key"]: m for m in result["metrics"]}
    assert metrics["latest_conviction"]["status"] == "red"
    assert metrics["latest_conviction"]["value"] == "No live conviction data available"
    assert metrics["connection"]["status"] == "red"  # never pulled
    assert result["status"] == "red"


def test_fresh_pipeline_is_green(factory: sessionmaker[Session]) -> None:
    now = dt.datetime(2026, 6, 23, 12, tzinfo=dt.UTC)
    with factory() as session:
        _seed_fresh(session, now)
        result = dh.data_health(session, provider_name="yfinance", now=now)
    metrics = {m["key"]: m for m in result["metrics"]}
    assert metrics["connection"]["status"] == "green"
    assert metrics["latest_scan"]["value"] == "scan-20260623"
    assert metrics["latest_conviction"]["status"] == "green"
    assert "NVDA" not in (metrics["latest_conviction"]["value"] or "")  # value is date (run)
    assert metrics["latest_conviction"]["value"].startswith("2026-06-23")
    assert metrics["latest_watchlist"]["value"] == "2026-06-23"
    assert result["status"] in {"green", "yellow"}  # cache empty -> yellow at worst


def test_stale_scan_degrades_connection(factory: sessionmaker[Session]) -> None:
    now = dt.datetime(2026, 6, 23, 12, tzinfo=dt.UTC)
    with factory() as session:
        session.add(
            ScanMetadata(
                scan_id="scan-old",
                provider="yfinance",
                universe="S&P 500",
                pull_timestamp=now - dt.timedelta(days=10),
                symbol_count=10,
                data_age_minutes=10 * 24 * 60.0,
                stale=True,
            )
        )
        session.commit()
        result = dh.data_health(session, provider_name="yfinance", now=now)
    metrics = {m["key"]: m for m in result["metrics"]}
    assert metrics["connection"]["status"] == "yellow"
    assert metrics["data_age"]["status"] in {"yellow", "red"}


def test_diagnostics_exposes_raw_values(factory: sessionmaker[Session]) -> None:
    now = dt.datetime(2026, 6, 23, 12, tzinfo=dt.UTC)
    with factory() as session:
        _seed_fresh(session, now)
        raw = dh.diagnostics(session, provider_name="yfinance")
    assert raw["provider"] == "yfinance"
    assert "bars" in raw["cache_path"]
    assert raw["database_path"]
    assert raw["latest_scan_id"] == "scan-20260623"
    assert raw["latest_conviction_run_id"] == "scan-20260623"


def test_routes_respond(factory: sessionmaker[Session]) -> None:
    app = create_app(session_factory=factory)
    client = TestClient(app)
    health = client.get("/data-health")
    assert health.status_code == 200
    assert "metrics" in health.json()
    diag = client.get("/data-health/diagnostics")
    assert diag.status_code == 200
    assert "cache_path" in diag.json()
