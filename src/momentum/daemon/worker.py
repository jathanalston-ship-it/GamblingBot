"""The market daemon — a resilient background worker owning the scan loop.

Runs on a dedicated daemon thread so it never blocks the API/UI. Each tick:

    determine market state → (in a scanning window) run one full cycle
    (pull → scan → conviction → trade health → watchlists → command center /
    portfolio / thesis journal all derive from the persisted scan) → publish a
    daemon event → sleep the state's interval.

Outside market hours it only re-checks the market state every closed-interval.
Pause/resume, manual scan, immediate refresh and graceful shutdown are all
event-driven (`threading.Event.wait` — a trigger interrupts any sleep).
Errors never kill the loop: failures are recorded, published, and retried with
capped exponential backoff — a temporary provider outage just becomes a chain
of recorded failures until data returns.

The cycle itself is injected (a callable), so the worker is testable with a
fake clock and a stub cycle — no network, no real sleeping.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from momentum.daemon.config import DaemonConfig
from momentum.daemon.market_state import MarketState, interval_seconds, market_state

_log = logging.getLogger("momentum.daemon")

Clock = Callable[[], dt.datetime]
Cycle = Callable[[MarketState, bool], dict[str, Any]]
Sleeper = Callable[[float], bool]  # wait(timeout) -> True when interrupted


class MarketDaemon:
    """Continuously running market-intelligence loop (dedicated thread)."""

    def __init__(
        self,
        cycle: Cycle,
        *,
        config: DaemonConfig | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config or DaemonConfig()
        self._cycle = cycle
        self._clock = clock or (lambda: dt.datetime.now(tz=dt.UTC))

        self._thread: threading.Thread | None = None
        self._wake = threading.Event()  # interrupts any sleep
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._manual = threading.Event()  # scan requested regardless of schedule
        self._lock = threading.Lock()

        self._events: deque[dict[str, Any]] = deque(maxlen=self.config.event_buffer)
        self._version = 0  # bumps on every published event (cheap UI change poll)
        self._cycles = 0
        self._failures = 0
        self._consecutive_failures = 0
        self._last_scan_at: dt.datetime | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._next_wake_at: dt.datetime | None = None
        self._current_state: MarketState | None = None
        self._scanning_now = False

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the worker thread (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="mrp-market-daemon", daemon=True)
            self._thread.start()
        self._publish("daemon", "started")

    def stop(self, *, timeout: float = 10.0) -> None:
        """Graceful shutdown: finish/abort the sleep, join the thread."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._publish("daemon", "stopped")

    def pause(self) -> None:
        self._paused.set()
        self._publish("daemon", "paused")

    def resume(self) -> None:
        self._paused.clear()
        self._wake.set()
        self._publish("daemon", "resumed")

    def trigger_scan(self) -> None:
        """Manual scan / immediate refresh: run a cycle now, schedule or not."""
        self._manual.set()
        self._wake.set()
        self._publish("daemon", "manual scan requested")

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stop.is_set()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    # ------------------------------------------------------------------ #
    # the loop
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        while not self._stop.is_set():
            now = self._clock()
            state = market_state(now)
            self._current_state = state
            manual = self._manual.is_set()
            if manual:
                self._manual.clear()

            should_scan = manual or (state.scanning and not self._paused.is_set())
            if should_scan:
                self._run_cycle(state, manual)

            delay = self._delay_after(state)
            self._next_wake_at = self._clock() + dt.timedelta(seconds=delay)
            interrupted = self._wake.wait(timeout=delay)
            if interrupted:
                self._wake.clear()

    def _run_cycle(self, state: MarketState, manual: bool) -> None:
        self._scanning_now = True
        started = self._clock()
        try:
            result = self._cycle(state, manual)
            with self._lock:
                self._cycles += 1
                self._consecutive_failures = 0
                self._last_scan_at = started
                self._last_result = result
                self._last_error = None
            self._publish(
                "scan",
                f"cycle complete ({state.value})",
                result={k: result[k] for k in sorted(result) if not k.startswith("_")},
            )
        except Exception as exc:  # noqa: BLE001 — the daemon must never die
            with self._lock:
                self._failures += 1
                self._consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"[:500]
            _log.warning("daemon cycle failed (%s): %s", state.value, exc)
            self._publish("error", self._last_error or "cycle failed")
        finally:
            self._scanning_now = False

    def _delay_after(self, state: MarketState) -> float:
        base = interval_seconds(
            state,
            scan_interval=self.config.scan_interval_seconds,
            closed_interval=self.config.closed_interval_seconds,
        )
        if self._consecutive_failures > 0 and state.scanning:
            backoff: float = min(
                self.config.backoff_base_seconds * float(2 ** (self._consecutive_failures - 1)),
                self.config.backoff_max_seconds,
            )
            return float(max(base, backoff))
        return base

    # ------------------------------------------------------------------ #
    # events + status (the UI feed)
    # ------------------------------------------------------------------ #
    def _publish(self, kind: str, message: str, **payload: Any) -> None:
        with self._lock:
            self._version += 1
            self._events.appendleft(
                {
                    "ts": self._clock().isoformat(),
                    "kind": kind,
                    "message": message,
                    **payload,
                }
            )

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)[:limit]

    def status(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            next_wake = self._next_wake_at
            return {
                "running": self.running,
                "paused": self.paused,
                "scanning_now": self._scanning_now,
                "market_state": (self._current_state or market_state(now)).value,
                "scan_interval_seconds": self.config.scan_interval_seconds,
                "closed_interval_seconds": self.config.closed_interval_seconds,
                "cycles": self._cycles,
                "failures": self._failures,
                "consecutive_failures": self._consecutive_failures,
                "last_scan_at": (self._last_scan_at.isoformat() if self._last_scan_at else None),
                "last_error": self._last_error,
                "next_wake_at": next_wake.isoformat() if next_wake else None,
                "seconds_to_next_wake": (
                    max(0.0, (next_wake - now).total_seconds()) if next_wake else None
                ),
                "version": self._version,
                "last_result": self._last_result,
            }
