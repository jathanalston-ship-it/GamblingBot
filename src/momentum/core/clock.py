"""Time abstraction decoupling business logic from wall-clock time.

The ``Clock`` is the primary defense against look-ahead bias: business code only
ever asks "what time is it now?" and may only use data stamped at or before that
moment. In a backtest the :class:`SimulatedClock` is advanced bar-by-bar by the
engine, so "now" is the bar being processed — never the future. In paper/live
the :class:`LiveClock` returns the real wall clock. The same strategy/risk code
runs against either.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class Clock(Protocol):
    """Anything that can report the current decision time."""

    def now(self) -> pd.Timestamp: ...


class SimulatedClock:
    """A clock the backtest engine advances explicitly, one bar at a time."""

    def __init__(self, start: pd.Timestamp | None = None) -> None:
        self._now = start

    def now(self) -> pd.Timestamp:
        if self._now is None:
            raise RuntimeError("SimulatedClock has not been set to a time yet")
        return self._now

    def set_time(self, ts: pd.Timestamp) -> None:
        """Move time forward to ``ts`` (must be monotonic non-decreasing)."""
        if self._now is not None and ts < self._now:
            raise ValueError(f"clock cannot move backward: {ts} < {self._now}")
        self._now = ts


class LiveClock:
    """Wall-clock time (UTC) for paper/live trading."""

    def now(self) -> pd.Timestamp:
        return pd.Timestamp.now(tz="UTC")
