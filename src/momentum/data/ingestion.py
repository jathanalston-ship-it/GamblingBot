"""Ingestion orchestrator: fetch -> validate -> cache, incremental & idempotent.

``DataIngestor`` is the layer's front door. It coordinates a
:class:`MarketDataProvider` with a :class:`BarCache` so that:

* **No duplicate downloads** — :meth:`BarCache.missing_ranges` is consulted
  first, and only the absent windows are fetched from the vendor.
* **Idempotent** — re-running an ingest over the same window is a cache read;
  merges de-duplicate on timestamp.
* **Incremental** — :meth:`DataIngestor.update` extends a symbol from its last
  cached bar to "now" in a single follow-on request.
* **Validated** — every freshly downloaded batch passes the quality gates
  before it is written, with the verdict surfaced on the result.

It returns lightweight :class:`IngestionResult` records so callers (the CLI,
the universe builder) get an auditable summary of what came from the vendor
versus the cache.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd

from momentum.data.cache import BarCache
from momentum.data.providers.base import DateLike, MarketDataProvider
from momentum.data.schema import (
    Adjustment,
    Timeframe,
    empty_bars,
    to_utc_timestamp,
)
from momentum.data.validation import BarQualityReport, validate_bars


@dataclass(slots=True)
class IngestionResult:
    """A summary of one symbol's ingest."""

    symbol: str
    timeframe: Timeframe
    rows_total: int
    rows_downloaded: int
    downloaded_ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    from_cache_only: bool = False
    report: BarQualityReport | None = None

    @property
    def hit_vendor(self) -> bool:
        return self.rows_downloaded > 0 or not self.from_cache_only


class DataIngestor:
    """Coordinates provider + cache to produce trusted, deduplicated bars."""

    def __init__(
        self,
        provider: MarketDataProvider,
        cache: BarCache,
        *,
        validate: bool = True,
        spike_threshold: float = 0.5,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.validate = validate
        self.spike_threshold = spike_threshold

    # -- single symbol ------------------------------------------------------ #
    def ingest(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
        *,
        force: bool = False,
    ) -> IngestionResult:
        """Ensure ``[start, end]`` for ``symbol`` is cached; download only gaps.

        Args:
            force: ignore the cache envelope and re-download the full window
                (the merge still de-duplicates, so this is safe).
        """
        req_start = to_utc_timestamp(start)
        req_end = to_utc_timestamp(end)

        if force:
            ranges = [(req_start, req_end)]
        else:
            ranges = self.cache.missing_ranges(symbol, timeframe, req_start, req_end)

        downloaded = 0
        done_ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        last_report: BarQualityReport | None = None

        for r_start, r_end in ranges:
            batch = self.provider.get_bars(symbol, r_start, r_end, timeframe, adjustment)
            if batch.empty:
                continue
            if self.validate:
                last_report = validate_bars(
                    batch,
                    symbol,
                    timeframe=timeframe,
                    spike_threshold=self.spike_threshold,
                )
            self.cache.write(symbol, timeframe, batch)
            downloaded += len(batch)
            done_ranges.append((batch.index[0], batch.index[-1]))

        merged = self.cache.read(symbol, timeframe, req_start, req_end)
        return IngestionResult(
            symbol=symbol.upper(),
            timeframe=timeframe,
            rows_total=len(merged),
            rows_downloaded=downloaded,
            downloaded_ranges=done_ranges,
            from_cache_only=downloaded == 0,
            report=last_report,
        )

    # -- many symbols ------------------------------------------------------- #
    def ingest_many(
        self,
        symbols: Iterable[str],
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
        *,
        force: bool = False,
    ) -> dict[str, IngestionResult]:
        """Ingest several symbols; returns one result per symbol."""
        return {s: self.ingest(s, start, end, timeframe, adjustment, force=force) for s in symbols}

    # -- incremental update ------------------------------------------------- #
    def update(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
        *,
        now: DateLike | None = None,
    ) -> IngestionResult:
        """Extend a cached symbol from its last bar to ``now`` (default: today).

        If nothing is cached yet, falls back to a one-year backfill.
        """
        end = to_utc_timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
        cov = self.cache.coverage(symbol, timeframe)
        if cov is None:
            start = end - pd.Timedelta(days=365)
        else:
            start = cov[1]  # last cached bar; overlap is de-duplicated on merge
        return self.ingest(symbol, start, end, timeframe, adjustment)

    # -- read-through ------------------------------------------------------- #
    def load(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        """Return bars for the window, downloading anything missing first."""
        self.ingest(symbol, start, end, timeframe, adjustment)
        return self.cache.read(symbol, timeframe, start, end)

    def load_current(self, symbol: str, timeframe: Timeframe = Timeframe.DAY) -> pd.DataFrame:
        """Fetch the latest bar straight from the vendor and cache it."""
        latest = self.provider.get_latest_bar(symbol, timeframe)
        if latest.empty:
            return empty_bars(extended=True)
        self.cache.write(symbol, timeframe, latest)
        return latest
