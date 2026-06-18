"""Local parquet cache for OHLCV bars.

Layout (one file per symbol+timeframe, columnar + compressed)::

    <root>/bars/<timeframe>/<SYMBOL>.parquet

The cache is the platform's defence against redundant vendor calls. Writes are
*idempotent*: new bars are merged into the existing file, de-duplicated on the
timestamp index (last wins), and re-sorted — so re-running an ingest is safe.
:meth:`BarCache.missing_ranges` reports exactly which sub-windows are absent so
the ingestor downloads only the gaps, never what it already has.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from momentum.core.exceptions import CacheError
from momentum.data.schema import (
    Timeframe,
    empty_bars,
    normalize_bars,
    to_utc_timestamp,
)


class BarCache:
    """Parquet-backed store of canonical bar frames."""

    def __init__(self, root: str | Path, *, subdir: str = "bars") -> None:
        self.root = Path(root) / subdir

    # -- paths -------------------------------------------------------------- #
    def path_for(self, symbol: str, timeframe: Timeframe) -> Path:
        return self.root / timeframe.value.lower() / f"{symbol.upper()}.parquet"

    def exists(self, symbol: str, timeframe: Timeframe) -> bool:
        return self.path_for(symbol, timeframe).exists()

    # -- reads -------------------------------------------------------------- #
    def read(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        """Return cached bars (optionally sliced to ``[start, end]``).

        Missing files yield an empty canonical frame rather than an error.
        """
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return empty_bars(extended=True)
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:  # corrupt file, missing engine, ...
            raise CacheError(f"failed to read {path}: {exc}") from exc
        frame = normalize_bars(frame)
        if start is not None:
            frame = frame[frame.index >= to_utc_timestamp(start)]
        if end is not None:
            frame = frame[frame.index <= to_utc_timestamp(end)]
        return frame

    def coverage(
        self, symbol: str, timeframe: Timeframe
    ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """``(first, last)`` cached timestamp, or ``None`` if nothing is cached."""
        frame = self.read(symbol, timeframe)
        if frame.empty:
            return None
        return frame.index[0], frame.index[-1]

    # -- writes ------------------------------------------------------------- #
    def write(self, symbol: str, timeframe: Timeframe, frame: pd.DataFrame) -> pd.DataFrame:
        """Merge ``frame`` into the cache and return the full merged result."""
        incoming = normalize_bars(frame)
        existing = self.read(symbol, timeframe)
        if existing.empty:
            merged = incoming
        elif incoming.empty:
            merged = existing
        else:
            # concat then keep-last dedup => incoming overwrites stale rows.
            merged = normalize_bars(pd.concat([existing, incoming]))
        path = self.path_for(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            merged.to_parquet(path, compression="snappy")
        except Exception as exc:
            raise CacheError(f"failed to write {path}: {exc}") from exc
        return merged

    # -- gap analysis ------------------------------------------------------- #
    def missing_ranges(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: object,
        end: object,
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """Sub-windows of ``[start, end]`` not already covered by the cache.

        Uses the cached ``[first, last]`` envelope only (it does not try to find
        interior holes — interior integrity is the validator's job). Returns the
        portions before ``first`` and/or after ``last`` that need downloading.
        An empty list means the request is fully satisfied locally.
        """
        req_start = to_utc_timestamp(start)
        req_end = to_utc_timestamp(end)
        if req_start > req_end:
            return []
        cov = self.coverage(symbol, timeframe)
        if cov is None:
            return [(req_start, req_end)]
        first, last = cov
        gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        if req_start < first:
            gaps.append((req_start, min(req_end, first - pd.Timedelta(microseconds=1))))
        if req_end > last:
            gaps.append((max(req_start, last + pd.Timedelta(microseconds=1)), req_end))
        return [(a, b) for a, b in gaps if a <= b]

    # -- maintenance -------------------------------------------------------- #
    def delete(self, symbol: str, timeframe: Timeframe) -> bool:
        """Remove a symbol's cached file. Returns whether anything was deleted."""
        path = self.path_for(symbol, timeframe)
        if path.exists():
            path.unlink()
            return True
        return False

    def symbols(self, timeframe: Timeframe) -> list[str]:
        """All symbols cached at ``timeframe`` (sorted)."""
        d = self.root / timeframe.value.lower()
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.parquet"))
