"""Certification service tests — real DB rows in, honest report out."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import certification_service
from momentum.certification import CertificationConfig
from momentum.daemon.market_state import market_state
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Alert, Base, Run, Trade
from momentum.persistence.models.market_data_provenance import MarketDataProvenance
from momentum.persistence.models.scan_stat import ScanStat

NOW = dt.datetime(2026, 7, 1, 18, 0, tzinfo=dt.UTC)  # Wednesday 14:00 ET
FAST = CertificationConfig(window_days=3)


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
    monkeypatch.setenv("MRP_PARENT_PID", "12345")  # desktop session: watchdog active
    return tmp_path


def _seed_perfect_operation(session: Session, *, days: float = 3.5) -> int:
    """One ScanStat per scanning minute — a flawless daemon."""
    cursor = NOW - dt.timedelta(days=days)
    step = dt.timedelta(minutes=1)
    n = 0
    rows = []
    while cursor < NOW:
        if market_state(cursor).scanning:
            rows.append(
                ScanStat(
                    scan_ts=cursor,
                    run_id="scan-x",
                    duration_ms=1500.0,
                    symbols_processed=50,
                    memory_mb=350.0,
                    degraded=False,
                )
            )
            n += 1
        cursor += step
    session.add_all(rows)
    session.commit()
    return n


def test_report_tracks_the_operational_metrics(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        scans = _seed_perfect_operation(session)
        session.add_all(
            [
                Trade(
                    run_id="r",
                    symbol="AAA",
                    direction="long",
                    entry_ts=NOW - dt.timedelta(days=1),
                    entry_price=100.0,
                    quantity=10,
                    initial_stop=95.0,
                    status="open",
                ),
                Trade(
                    run_id="r",
                    symbol="BBB",
                    direction="long",
                    entry_ts=NOW - dt.timedelta(days=2),
                    entry_price=50.0,
                    quantity=10,
                    initial_stop=47.0,
                    status="closed",
                    exit_ts=NOW - dt.timedelta(days=1),
                    exit_price=55.0,
                ),
                Alert(
                    ts=NOW - dt.timedelta(hours=3),
                    severity="warning",
                    kind="delta",
                    title="t",
                    description="d",
                    dedupe_key="k1",
                ),
                Run(
                    run_id="failed-job",
                    mode="scan",
                    as_of=NOW.date(),
                    status="failed",
                    started_at=NOW - dt.timedelta(hours=5),
                ),
                MarketDataProvenance(
                    symbol="CCC",
                    provider="yfinance",
                    request_timestamp=NOW - dt.timedelta(hours=4),
                    bar_count=0,
                    error="HTTP 500",
                ),
            ]
        )
        session.commit()

        report = certification_service.certification_report(session, now=NOW, config=FAST)

    assert report["scans_completed"] == scans
    assert report["trades_opened"] == 2
    assert report["trades_closed"] == 1
    assert report["alerts_generated"] == 1
    assert report["warnings"] == 1
    assert report["api_failures"] == 1
    assert report["errors"] == 1  # the failed run
    assert report["provider_failures"] == 1
    assert report["status"] == "certified"  # 3-day window fully covered
    assert report["certified"] is True


def test_crash_history_counts_and_resets(factory: sessionmaker[Session], user_dir: Path) -> None:
    crash_at = (NOW - dt.timedelta(days=1)).isoformat()
    (user_dir / "automation_state.json").write_text(
        json.dumps(
            {
                "last_heartbeat": NOW.isoformat(),
                "recoveries": [
                    {"recovered_at": crash_at, "downtime_seconds": 3600, "missed_scans": 60}
                ],
            }
        )
    )
    with factory() as session:
        _seed_perfect_operation(session)
        report = certification_service.certification_report(session, now=NOW, config=FAST)
    assert report["certified"] is False
    assert report["status"] == "in_progress"
    assert report["streak_days"] == 1  # the crash zeroed everything before today


def test_duplicate_open_trades_fail_certification(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        _seed_perfect_operation(session)
        for i in range(2):
            session.add(
                Trade(
                    run_id=f"r{i}",
                    symbol="AAA",
                    direction="long",
                    entry_ts=NOW - dt.timedelta(days=1, minutes=i),
                    entry_price=100.0,
                    quantity=10,
                    initial_stop=95.0,
                    status="open",
                )
            )
        session.commit()
        report = certification_service.certification_report(session, now=NOW, config=FAST)
    assert report["status"] == "failing"
    duplicate = next(r for r in report["requirements"] if r["key"] == "no_duplicate_trades")
    assert duplicate["passed"] is False


def test_bare_cli_session_cannot_certify(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MRP_PARENT_PID", raising=False)
    with factory() as session:
        _seed_perfect_operation(session)
        report = certification_service.certification_report(session, now=NOW, config=FAST)
    assert report["status"] == "failing"
    orphan = next(r for r in report["requirements"] if r["key"] == "no_orphaned_backend")
    assert orphan["passed"] is False


def test_endpoint_serves_the_report(factory: sessionmaker[Session]) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app

    client = TestClient(create_app(session_factory=factory))
    response = client.get("/certification")
    assert response.status_code == 200
    body = response.json()
    assert body["certified"] is False  # a fresh install is never certified
    assert {r["key"] for r in body["requirements"]} >= {
        "no_crashes",
        "no_missed_scans",
        "no_database_corruption",
        "window_complete",
    }
