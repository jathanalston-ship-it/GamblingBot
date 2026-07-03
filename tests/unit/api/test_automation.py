"""Automation Mode tests: resilience state, recovery math, preflight health."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from momentum.api import automation_health_service, automation_state

# A Wednesday. 14:00 UTC = 10:00 ET (regular session, EDT).
WEDNESDAY_OPEN = dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.UTC)
# Saturday — the market never scans.
SATURDAY = dt.datetime(2026, 7, 4, 14, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# resilience state
# --------------------------------------------------------------------------- #
def test_heartbeat_persists_and_clean_shutdown_marks(user_dir: Path) -> None:
    automation_state.record_heartbeat(ts=WEDNESDAY_OPEN, last_scan=WEDNESDAY_OPEN)
    raw = json.loads((user_dir / "automation_state.json").read_text())
    assert raw["clean_shutdown"] is False
    assert raw["last_scan"] == WEDNESDAY_OPEN.isoformat()
    automation_state.mark_clean_shutdown(ts=WEDNESDAY_OPEN)
    raw = json.loads((user_dir / "automation_state.json").read_text())
    assert raw["clean_shutdown"] is True


def test_first_run_and_clean_shutdown_are_not_recoveries(user_dir: Path) -> None:
    assert automation_state.detect_recovery(now=WEDNESDAY_OPEN) is None  # first run
    automation_state.record_heartbeat(ts=WEDNESDAY_OPEN)
    automation_state.mark_clean_shutdown(ts=WEDNESDAY_OPEN)
    later = WEDNESDAY_OPEN + dt.timedelta(hours=5)
    assert automation_state.detect_recovery(now=later) is None  # deliberate stop


def test_fast_restart_is_not_a_crash(user_dir: Path) -> None:
    automation_state.record_heartbeat(ts=WEDNESDAY_OPEN)
    soon = WEDNESDAY_OPEN + dt.timedelta(minutes=5)
    assert automation_state.detect_recovery(now=soon) is None


def test_unclean_gap_records_downtime_and_missed_scans(user_dir: Path) -> None:
    automation_state.record_heartbeat(ts=WEDNESDAY_OPEN, interval_seconds=60.0)
    later = WEDNESDAY_OPEN + dt.timedelta(hours=2)  # died mid-session
    recovery = automation_state.detect_recovery(now=later)
    assert recovery is not None
    assert recovery["downtime_seconds"] == pytest.approx(7200.0)
    # Two regular-session hours at 60s cadence ≈ 120 missed scans.
    assert 115 <= recovery["missed_scans"] <= 120
    # The record persists for the UI...
    assert automation_state.last_recovery() == recovery
    # ...and the SAME gap is never reported twice.
    assert automation_state.detect_recovery(now=later + dt.timedelta(seconds=1)) is None


def test_weekend_outage_misses_zero_scans(user_dir: Path) -> None:
    friday_close = dt.datetime(2026, 7, 4, 0, 30, tzinfo=dt.UTC)  # Fri 20:30 ET
    automation_state.record_heartbeat(ts=friday_close, interval_seconds=60.0)
    sunday = friday_close + dt.timedelta(hours=40)
    recovery = automation_state.detect_recovery(now=sunday)
    assert recovery is not None
    assert recovery["missed_scans"] == 0  # market was closed the whole time


def test_missed_scans_pure_math() -> None:
    hour = automation_state.missed_scans_between(
        WEDNESDAY_OPEN, WEDNESDAY_OPEN + dt.timedelta(hours=1), interval_seconds=60.0
    )
    assert hour == 60
    assert (
        automation_state.missed_scans_between(
            SATURDAY, SATURDAY + dt.timedelta(hours=3), interval_seconds=60.0
        )
        == 0
    )
    assert automation_state.missed_scans_between(WEDNESDAY_OPEN, WEDNESDAY_OPEN) == 0


# --------------------------------------------------------------------------- #
# preflight health
# --------------------------------------------------------------------------- #
class _Daemon:
    def __init__(self, *, running: bool = True, paused: bool = False) -> None:
        self._status = {"running": running, "paused": paused}

    def status(self) -> dict[str, Any]:
        return dict(self._status)


def _stub_probe(monkeypatch: pytest.MonkeyPatch, *, ok: bool, drift_seconds: float = 0.0) -> None:
    from email.utils import format_datetime

    def probe(url: str) -> tuple[int | None, str | None, float]:
        if not ok:
            return None, None, 3000.0
        remote = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=drift_seconds)
        return 200, format_datetime(remote), 42.0

    monkeypatch.setattr(automation_health_service, "_probe", probe)


def test_all_healthy_with_running_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probe(monkeypatch, ok=True)
    report = automation_health_service.check_all(daemon=_Daemon())
    assert report["overall"] == "healthy"
    names = {c["name"] for c in report["checks"]}
    assert names == {
        "backend",
        "scheduler",
        "sleep_prevention",
        "internet",
        "data_provider",
        "clock_sync",
        "market_calendar",
    }
    assert all(c["detail"] for c in report["checks"])  # every grade is explained


def test_offline_is_critical_and_blocks_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probe(monkeypatch, ok=False)
    report = automation_health_service.check_all(daemon=_Daemon())
    assert report["overall"] == "critical"
    failures = automation_health_service.preflight_failures(daemon=_Daemon())
    assert {f["name"] for f in failures} == {"internet", "data_provider"}


def test_clock_drift_grades(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probe(monkeypatch, ok=True, drift_seconds=300.0)
    report = automation_health_service.check_all(daemon=_Daemon())
    clock = next(c for c in report["checks"] if c["name"] == "clock_sync")
    assert clock["status"] == "warning"
    _stub_probe(monkeypatch, ok=True, drift_seconds=1200.0)
    clock = next(
        c
        for c in automation_health_service.check_all(daemon=_Daemon())["checks"]
        if c["name"] == "clock_sync"
    )
    assert clock["status"] == "critical"


def test_paused_daemon_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probe(monkeypatch, ok=True)
    report = automation_health_service.check_all(daemon=_Daemon(paused=True))
    scheduler = next(c for c in report["checks"] if c["name"] == "scheduler")
    assert scheduler["status"] == "warning"


def test_enabling_autopilot_refused_when_critical(
    monkeypatch: pytest.MonkeyPatch, user_dir: Path
) -> None:
    """The Long-Running gate: a failed preflight refuses the start and says why."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from momentum.api.app import create_app
    from momentum.persistence.database import create_session_factory
    from momentum.persistence.models import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    client = TestClient(create_app(session_factory=create_session_factory(engine)))

    _stub_probe(monkeypatch, ok=False)
    refused = client.put("/settings/autopilot", json={"enabled": True})
    assert refused.status_code == 409
    assert "preflight failed" in refused.json()["detail"]
    assert "internet" in refused.json()["detail"]  # the reason is named
    assert client.get("/settings/autopilot").json()["enabled"] is False  # NOT started

    _stub_probe(monkeypatch, ok=True)
    # The bare-API daemon is a warning (not critical) — enabling now succeeds.
    accepted = client.put("/settings/autopilot", json={"enabled": True})
    assert accepted.status_code == 200
    assert accepted.json()["enabled"] is True

    report = client.get("/automation/health").json()
    assert {c["name"] for c in report["checks"]} >= {"backend", "scheduler", "internet"}
    recovery = client.get("/automation/recovery").json()
    assert recovery["last_recovery"] is None
