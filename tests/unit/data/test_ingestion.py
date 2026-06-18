"""Tests for the ingestion orchestrator (incremental, idempotent, dedup)."""

from __future__ import annotations

import pandas as pd

from momentum.data.cache import BarCache
from momentum.data.ingestion import DataIngestor
from momentum.data.providers.base import MarketDataProvider
from momentum.data.schema import (
    Adjustment,
    Timeframe,
    empty_bars,
    normalize_bars,
    to_utc_timestamp,
)


class RecordingProvider(MarketDataProvider):
    """A fake vendor serving slices of a fixed dataset, recording every call."""

    name = "recording"

    def __init__(self, dataset: pd.DataFrame) -> None:
        self.dataset = normalize_bars(dataset)
        self.calls: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def get_bars(
        self,
        symbol: str,
        start,
        end,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        s, e = to_utc_timestamp(start), to_utc_timestamp(end)
        self.calls.append((s, e))
        mask = (self.dataset.index >= s) & (self.dataset.index <= e)
        return self.dataset[mask]

    def get_latest_bar(self, symbol: str, timeframe: Timeframe = Timeframe.DAY) -> pd.DataFrame:
        return self.dataset.iloc[-1:] if not self.dataset.empty else empty_bars()


def _dataset(n: int = 20, start: str = "2023-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    closes = [100.0 + i for i in range(n)]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * n,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return normalize_bars(df)


def test_first_ingest_downloads_and_caches(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    result = ingestor.ingest("AAPL", "2023-01-02", "2023-01-11", Timeframe.DAY)
    assert result.rows_downloaded == 10
    assert len(provider.calls) == 1
    assert result.report is not None and result.report.ok


def test_reingest_is_cache_only(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    ingestor.ingest("AAPL", "2023-01-02", "2023-01-11", Timeframe.DAY)
    provider.calls.clear()
    result = ingestor.ingest("AAPL", "2023-01-02", "2023-01-11", Timeframe.DAY)
    assert result.from_cache_only
    assert result.rows_downloaded == 0
    assert provider.calls == []  # no duplicate download


def test_incremental_only_downloads_gap(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    ingestor.ingest("AAPL", "2023-01-02", "2023-01-06", Timeframe.DAY)  # first 5
    provider.calls.clear()
    result = ingestor.ingest("AAPL", "2023-01-02", "2023-01-11", Timeframe.DAY)
    # only the tail gap is fetched, and its start is after the cached last bar
    assert len(provider.calls) == 1
    assert provider.calls[0][0] > pd.Timestamp("2023-01-06", tz="UTC")
    assert result.rows_total == 10


def test_force_redownloads_full_window(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    ingestor.ingest("AAPL", "2023-01-02", "2023-01-11", Timeframe.DAY)
    provider.calls.clear()
    ingestor.ingest("AAPL", "2023-01-02", "2023-01-11", Timeframe.DAY, force=True)
    assert provider.calls == [
        (pd.Timestamp("2023-01-02", tz="UTC"), pd.Timestamp("2023-01-11", tz="UTC"))
    ]


def test_update_extends_from_last_bar(tmp_path) -> None:
    provider = RecordingProvider(_dataset(n=20))
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    ingestor.ingest("AAPL", "2023-01-02", "2023-01-06", Timeframe.DAY)
    provider.calls.clear()
    result = ingestor.update("AAPL", Timeframe.DAY, now="2023-01-21")
    assert result.rows_downloaded > 0
    # the gap fetch starts at (just after) the last cached bar, never before it
    assert provider.calls[0][0] >= pd.Timestamp("2023-01-06", tz="UTC")
    assert provider.calls[0][0] < pd.Timestamp("2023-01-07", tz="UTC")


def test_ingest_many(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    results = ingestor.ingest_many(["AAPL", "MSFT"], "2023-01-02", "2023-01-06")
    assert set(results) == {"AAPL", "MSFT"}
    assert all(r.rows_total == 5 for r in results.values())


def test_load_is_read_through(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    bars = ingestor.load("AAPL", "2023-01-02", "2023-01-06", Timeframe.DAY)
    assert len(bars) == 5
    assert bars.index.is_monotonic_increasing


def test_load_current(tmp_path) -> None:
    provider = RecordingProvider(_dataset())
    ingestor = DataIngestor(provider, BarCache(tmp_path))
    latest = ingestor.load_current("AAPL", Timeframe.DAY)
    assert len(latest) == 1
    # it was cached too
    assert not ingestor.cache.read("AAPL", Timeframe.DAY).empty
