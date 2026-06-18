"""Tests for the parquet bar cache."""

from __future__ import annotations

import pandas as pd

from momentum.data.cache import BarCache
from momentum.data.schema import Timeframe


def test_write_then_read_roundtrip(tmp_path, make_bars) -> None:
    cache = BarCache(tmp_path)
    bars = make_bars(5)
    cache.write("aapl", Timeframe.DAY, bars)
    out = cache.read("AAPL", Timeframe.DAY)
    pd.testing.assert_frame_equal(out, bars)


def test_read_missing_returns_empty(tmp_path) -> None:
    cache = BarCache(tmp_path)
    assert cache.read("NOPE", Timeframe.DAY).empty
    assert cache.coverage("NOPE", Timeframe.DAY) is None


def test_write_merges_and_dedups(tmp_path, make_bars) -> None:
    cache = BarCache(tmp_path)
    first = make_bars(3, start="2023-01-02")
    cache.write("AAPL", Timeframe.DAY, first)
    # overlapping window with a changed close on the shared last day
    second = make_bars(3, start="2023-01-04", base=200.0)
    merged = cache.write("AAPL", Timeframe.DAY, second)
    assert merged.index.is_monotonic_increasing
    assert not merged.index.has_duplicates
    # 2023-01-02..01-06 => 5 unique days
    assert len(merged) == 5
    # overwritten day takes the newer (base=200) value
    overlap_day = pd.Timestamp("2023-01-04", tz="UTC")
    assert merged.loc[overlap_day, "close"] == 200.0


def test_read_slices_by_range(tmp_path, make_bars) -> None:
    cache = BarCache(tmp_path)
    cache.write("AAPL", Timeframe.DAY, make_bars(10))
    sliced = cache.read("AAPL", Timeframe.DAY, "2023-01-04", "2023-01-06")
    assert len(sliced) == 3


def test_coverage(tmp_path, make_bars) -> None:
    cache = BarCache(tmp_path)
    cache.write("AAPL", Timeframe.DAY, make_bars(4, start="2023-01-02"))
    first, last = cache.coverage("AAPL", Timeframe.DAY)
    assert first == pd.Timestamp("2023-01-02", tz="UTC")
    assert last == pd.Timestamp("2023-01-05", tz="UTC")


class TestMissingRanges:
    def test_nothing_cached_returns_full_window(self, tmp_path) -> None:
        cache = BarCache(tmp_path)
        gaps = cache.missing_ranges("AAPL", Timeframe.DAY, "2023-01-02", "2023-01-10")
        assert len(gaps) == 1
        assert gaps[0][0] == pd.Timestamp("2023-01-02", tz="UTC")

    def test_fully_covered_returns_empty(self, tmp_path, make_bars) -> None:
        cache = BarCache(tmp_path)
        cache.write("AAPL", Timeframe.DAY, make_bars(10, start="2023-01-02"))
        gaps = cache.missing_ranges("AAPL", Timeframe.DAY, "2023-01-03", "2023-01-09")
        assert gaps == []

    def test_tail_gap(self, tmp_path, make_bars) -> None:
        cache = BarCache(tmp_path)
        cache.write("AAPL", Timeframe.DAY, make_bars(3, start="2023-01-02"))  # ..01-04
        gaps = cache.missing_ranges("AAPL", Timeframe.DAY, "2023-01-02", "2023-01-10")
        assert len(gaps) == 1
        assert gaps[0][0] > pd.Timestamp("2023-01-04", tz="UTC")
        assert gaps[0][1] == pd.Timestamp("2023-01-10", tz="UTC")

    def test_both_ends_gap(self, tmp_path, make_bars) -> None:
        cache = BarCache(tmp_path)
        cache.write("AAPL", Timeframe.DAY, make_bars(3, start="2023-01-05"))  # 01-05..07
        gaps = cache.missing_ranges("AAPL", Timeframe.DAY, "2023-01-01", "2023-01-12")
        assert len(gaps) == 2


def test_delete_and_symbols(tmp_path, make_bars) -> None:
    cache = BarCache(tmp_path)
    cache.write("AAPL", Timeframe.DAY, make_bars(2))
    cache.write("MSFT", Timeframe.DAY, make_bars(2))
    assert cache.symbols(Timeframe.DAY) == ["AAPL", "MSFT"]
    assert cache.delete("AAPL", Timeframe.DAY) is True
    assert cache.delete("AAPL", Timeframe.DAY) is False
    assert cache.symbols(Timeframe.DAY) == ["MSFT"]
