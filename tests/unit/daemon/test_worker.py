"""Tests for the market-daemon worker: scheduling, controls, error recovery.

Real (tiny) sleeps + a fixed injected clock pinned inside/outside market hours
keep these deterministic and fast — no network, no real scanning.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

from momentum.daemon import DaemonConfig, MarketDaemon, MarketState

ET = ZoneInfo("America/New_York")

OPEN_HOURS = dt.datetime(2026, 7, 1, 12, 0, tzinfo=ET).astimezone(dt.UTC)  # Wed noon ET
CLOSED_HOURS = dt.datetime(2026, 7, 1, 22, 0, tzinfo=ET).astimezone(dt.UTC)  # Wed 10pm ET

FAST = DaemonConfig(
    scan_interval_seconds=0.01,
    closed_interval_seconds=0.02,
    backoff_base_seconds=0.05,
    backoff_max_seconds=0.2,
)


class CycleSpy:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.calls: list[tuple[MarketState, bool]] = []
        self.fail_times = fail_times
        self.ran = threading.Event()

    def __call__(self, state: MarketState, manual: bool) -> dict[str, Any]:
        self.calls.append((state, manual))
        self.ran.set()
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("temporary Yahoo failure")
        return {"cycle": len(self.calls)}


def _wait(predicate, timeout: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_scans_during_market_hours_and_stops_gracefully() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: OPEN_HOURS)
    daemon.start()
    assert _wait(lambda: len(spy.calls) >= 3)
    daemon.stop(timeout=2.0)
    assert not daemon.running
    assert all(state is MarketState.REGULAR for state, _ in spy.calls)
    assert daemon.status()["cycles"] >= 3
    assert daemon.status()["last_error"] is None


def test_never_scans_while_closed_but_still_wakes() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: CLOSED_HOURS)
    daemon.start()
    time.sleep(0.15)  # several closed-interval wakes
    daemon.stop(timeout=2.0)
    assert spy.calls == []  # only market-state checks, no scanning
    assert daemon.status()["market_state"] == "closed"


def test_pause_blocks_scanning_resume_restores_it() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: OPEN_HOURS)
    daemon.pause()
    daemon.start()
    time.sleep(0.1)
    assert spy.calls == []  # paused — no cycles despite market hours
    daemon.resume()
    assert _wait(lambda: len(spy.calls) >= 1)
    daemon.stop(timeout=2.0)


def test_manual_scan_works_even_when_closed_or_paused() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: CLOSED_HOURS)
    daemon.pause()
    daemon.start()
    daemon.trigger_scan()
    assert _wait(lambda: len(spy.calls) >= 1)
    daemon.stop(timeout=2.0)
    state, manual = spy.calls[0]
    assert manual is True
    assert state is MarketState.CLOSED


def test_recovers_automatically_after_errors() -> None:
    spy = CycleSpy(fail_times=2)  # two consecutive provider failures, then healthy
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: OPEN_HOURS)
    daemon.start()
    assert _wait(lambda: len(spy.calls) >= 3, timeout=5.0)
    assert _wait(lambda: daemon.status()["consecutive_failures"] == 0, timeout=5.0)
    daemon.stop(timeout=2.0)
    status = daemon.status()
    assert status["failures"] == 2
    assert status["cycles"] >= 1  # kept scanning after the outage
    assert any(e["kind"] == "error" for e in daemon.events())


def test_backoff_grows_and_is_capped() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: OPEN_HOURS)
    daemon._consecutive_failures = 1
    assert daemon._delay_after(MarketState.REGULAR) == 0.05
    daemon._consecutive_failures = 2
    assert daemon._delay_after(MarketState.REGULAR) == 0.1
    daemon._consecutive_failures = 10
    assert daemon._delay_after(MarketState.REGULAR) == 0.2  # capped
    daemon._consecutive_failures = 0
    assert daemon._delay_after(MarketState.REGULAR) == 0.01


def test_status_and_events_surface_everything() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: OPEN_HOURS)
    daemon.start()
    assert _wait(lambda: daemon.status()["cycles"] >= 1)
    status = daemon.status()
    assert status["running"] is True
    assert status["market_state"] == "regular"
    assert status["last_scan_at"] is not None
    assert status["last_result"] is not None
    assert status["version"] > 0
    daemon.stop(timeout=2.0)
    kinds = {e["kind"] for e in daemon.events()}
    assert "scan" in kinds and "daemon" in kinds


def test_start_is_idempotent() -> None:
    spy = CycleSpy()
    daemon = MarketDaemon(spy, config=FAST, clock=lambda: CLOSED_HOURS)
    daemon.start()
    daemon.start()
    daemon.stop(timeout=2.0)
