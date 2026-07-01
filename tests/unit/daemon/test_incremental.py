"""Tests for incremental reanalysis: fingerprints, cache reuse, change detection."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from momentum.daemon import CachingProvider, IncrementalCache

T0 = dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.UTC)


def _bars(last_close: float = 100.0, n: int = 50, end: str = "2026-06-30") -> pd.DataFrame:
    idx = pd.date_range(end=end, periods=n, freq="B")
    close = np.linspace(90.0, last_close, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1e6),
        },
        index=idx,
    )


class CountingProvider:
    name = "stub"

    def __init__(self) -> None:
        self.calls = 0
        self.frame = _bars()

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        self.calls += 1
        return self.frame


def test_first_pull_is_first_seen_then_unchanged() -> None:
    cache = IncrementalCache()
    assert cache.record("AAPL", _bars(), now=T0) == "first_seen"
    assert cache.record("AAPL", _bars(), now=T0) == "unchanged"


def test_new_bar_timestamp_is_changed() -> None:
    cache = IncrementalCache()
    cache.record("AAPL", _bars(end="2026-06-30"), now=T0)
    assert cache.record("AAPL", _bars(end="2026-07-01"), now=T0) == "changed"


def test_price_move_beyond_threshold_is_changed() -> None:
    cache = IncrementalCache(price_change_threshold=0.001)
    cache.record("AAPL", _bars(last_close=100.0), now=T0)
    assert cache.record("AAPL", _bars(last_close=100.05), now=T0) == "unchanged"  # 0.05%
    assert cache.record("AAPL", _bars(last_close=100.5), now=T0) == "changed"  # 0.5%


def test_bars_reused_within_max_age_only() -> None:
    cache = IncrementalCache()
    cache.record("AAPL", _bars(), now=T0)
    assert cache.bars_if_fresh("AAPL", now=T0 + dt.timedelta(seconds=30), max_age=45) is not None
    assert cache.bars_if_fresh("AAPL", now=T0 + dt.timedelta(seconds=60), max_age=45) is None
    assert cache.bars_if_fresh("AAPL", now=T0, max_age=0) is None  # reuse disabled


def test_caching_provider_hits_and_misses() -> None:
    inner = CountingProvider()
    cache = IncrementalCache()
    now = {"t": T0}
    provider = CachingProvider(inner, cache, max_age_seconds=45, clock=lambda: now["t"])

    provider.get_bars("AAPL", "2026-01-01", "2026-07-01")  # miss (cold)
    provider.get_bars("AAPL", "2026-01-01", "2026-07-01")  # hit (fresh)
    assert inner.calls == 1
    metrics = provider.metrics()
    assert metrics["cache_hits"] == 1 and metrics["cache_misses"] == 1
    assert metrics["cache_hit_rate"] == 0.5

    now["t"] = T0 + dt.timedelta(seconds=120)  # cache too old now
    provider.get_bars("AAPL", "2026-01-01", "2026-07-01")
    assert inner.calls == 2


def test_change_report_classifies_symbols() -> None:
    inner = CountingProvider()
    cache = IncrementalCache()
    provider = CachingProvider(inner, cache, max_age_seconds=0, clock=lambda: T0)

    provider.get_bars("AAPL", "a", "b")
    report = provider.report()
    assert report.first_seen == ("AAPL",)
    assert report.any_changed

    provider.reset_cycle()
    provider.get_bars("AAPL", "a", "b")  # identical frame
    report = provider.report()
    assert report.unchanged == ("AAPL",)
    assert not report.any_changed

    provider.reset_cycle()
    inner.frame = _bars(last_close=120.0, end="2026-07-01")
    provider.get_bars("AAPL", "a", "b")
    report = provider.report()
    assert report.changed == ("AAPL",)
    assert report.to_dict() == {"changed": 1, "unchanged": 0, "first_seen": 0}


def test_cache_clear_and_size() -> None:
    cache = IncrementalCache()
    cache.record("AAPL", _bars(), now=T0)
    cache.record("MSFT", _bars(), now=T0)
    assert cache.size() == 2
    cache.clear()
    assert cache.size() == 0
