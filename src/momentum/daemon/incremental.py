"""Incremental reanalysis — don't rebuild the world every minute.

Two cooperating pieces keep continuous scanning cheap **without changing the
results**:

* :class:`IncrementalCache` fingerprints every symbol's bars (newest bar
  timestamp + last close) after each pull. Comparing fingerprints across
  cycles tells the daemon exactly which symbols actually changed; when
  *nothing* changed (typical outside regular hours, and between provider
  updates) the entire analysis pass is skipped and the previous results —
  conviction, analogs, trade-management state, watchlists — remain valid and
  untouched, which is by construction identical to recomputing them.
* :class:`CachingProvider` wraps the real market-data provider: within
  ``bar_reuse_seconds`` of the last pull a symbol's bars are served from
  memory (a cache hit — no API call); older entries are pulled live. Because
  the wrapper implements the normal provider interface, the full scan pipeline
  runs unchanged on top of it, so an incremental scan and a full scan produce
  byte-identical persistence.

A price move beyond ``price_change_threshold`` (fraction) always counts as
changed even when the bar timestamp is unchanged (intraday daily-bar updates).
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from momentum.data.providers.base import DateLike, MarketDataProvider
from momentum.data.schema import Adjustment, Timeframe


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """What identifies a symbol's data as "the same" across cycles."""

    bar_timestamp: str | None  # ISO of the newest bar
    last_close: float | None
    pulled_at: dt.datetime


@dataclass(frozen=True, slots=True)
class ChangeReport:
    """Which symbols actually changed between two consecutive cycles."""

    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    first_seen: tuple[str, ...]

    @property
    def any_changed(self) -> bool:
        return bool(self.changed or self.first_seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": len(self.changed),
            "unchanged": len(self.unchanged),
            "first_seen": len(self.first_seen),
        }


def _fingerprint_of(frame: pd.DataFrame | None, now: dt.datetime) -> Fingerprint:
    if frame is None or frame.empty or "close" not in frame.columns:
        return Fingerprint(bar_timestamp=None, last_close=None, pulled_at=now)
    ts = pd.Timestamp(frame.index[-1])
    return Fingerprint(
        bar_timestamp=ts.isoformat(),
        last_close=float(frame["close"].iloc[-1]),
        pulled_at=now,
    )


def _changed(prev: Fingerprint, new: Fingerprint, *, threshold: float) -> bool:
    if prev.bar_timestamp != new.bar_timestamp:
        return True
    if prev.last_close is None or new.last_close is None:
        return prev.last_close != new.last_close
    if prev.last_close == 0:
        return new.last_close != 0
    return abs(new.last_close - prev.last_close) / abs(prev.last_close) > threshold


@dataclass
class IncrementalCache:
    """Per-symbol fingerprints + last bars, shared across daemon cycles."""

    price_change_threshold: float = 0.0005
    _fingerprints: dict[str, Fingerprint] = field(default_factory=dict)
    _bars: dict[str, pd.DataFrame] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def bars_if_fresh(
        self, symbol: str, *, now: dt.datetime, max_age: float
    ) -> pd.DataFrame | None:
        """The cached frame when it was pulled within ``max_age`` seconds."""
        with self._lock:
            fp = self._fingerprints.get(symbol.upper())
            if fp is None or max_age <= 0:
                return None
            if (now - fp.pulled_at).total_seconds() > max_age:
                return None
            return self._bars.get(symbol.upper())

    def record(self, symbol: str, frame: pd.DataFrame | None, *, now: dt.datetime) -> str:
        """Store the pull; classify it as 'changed' / 'unchanged' / 'first_seen'."""
        sym = symbol.upper()
        new = _fingerprint_of(frame, now)
        with self._lock:
            prev = self._fingerprints.get(sym)
            self._fingerprints[sym] = new
            if frame is not None and not frame.empty:
                self._bars[sym] = frame
            if prev is None:
                return "first_seen"
            if _changed(prev, new, threshold=self.price_change_threshold):
                return "changed"
            return "unchanged"

    def clear(self) -> None:
        with self._lock:
            self._fingerprints.clear()
            self._bars.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._fingerprints)


class CachingProvider(MarketDataProvider):
    """A provider wrapper that reuses fresh in-memory bars and counts changes.

    Serves :meth:`get_bars` from the :class:`IncrementalCache` when the last
    pull is younger than ``max_age_seconds`` (a cache hit — zero API calls);
    otherwise delegates to the wrapped provider and records the fresh
    fingerprint. After a cycle, :meth:`report` says exactly which symbols
    changed and how much work was reused.
    """

    name = "incremental"

    def __init__(
        self,
        inner: MarketDataProvider,
        cache: IncrementalCache,
        *,
        max_age_seconds: float,
        clock: Any = None,
    ) -> None:
        self.inner = inner
        self.cache = cache
        self.max_age_seconds = max_age_seconds
        self._clock = clock or (lambda: dt.datetime.now(tz=dt.UTC))
        self.label = f"{getattr(inner, 'name', 'provider')}+incremental"
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._status: dict[str, str] = {}

    def reset_cycle(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._status = {}

    def get_bars(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        now = self._clock()
        cached = self.cache.bars_if_fresh(symbol, now=now, max_age=self.max_age_seconds)
        if cached is not None:
            with self._lock:
                self._hits += 1
                self._status[symbol.upper()] = "unchanged"  # reused = definitionally same
            return cached
        frame = self.inner.get_bars(symbol, start, end, timeframe, adjustment)
        status = self.cache.record(symbol, frame, now=now)
        with self._lock:
            self._misses += 1
            self._status[symbol.upper()] = status
        return frame

    def report(self) -> ChangeReport:
        with self._lock:
            status = dict(self._status)
        return ChangeReport(
            changed=tuple(s for s, st in status.items() if st == "changed"),
            unchanged=tuple(s for s, st in status.items() if st == "unchanged"),
            first_seen=tuple(s for s, st in status.items() if st == "first_seen"),
        )

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            hits, misses = self._hits, self._misses
        total = hits + misses
        return {
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_hit_rate": round(hits / total, 4) if total else 0.0,
        }
