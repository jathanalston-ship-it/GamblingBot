"""Tests for the watchlist-performance configuration."""

from __future__ import annotations

import pytest

from momentum.watchlist_performance import WatchlistPerformanceConfig, default_config


def test_default_loads_and_hashes():
    cfg = default_config()
    assert cfg.day_window < cfg.week_window < cfg.month_window
    assert cfg.config_hash() == default_config().config_hash()
    assert cfg.conviction_buckets[-1] == (80, 100)


def test_windows_must_increase():
    with pytest.raises(ValueError, match="windows must strictly increase"):
        WatchlistPerformanceConfig(day_window=5, week_window=2)


def test_buckets_must_be_ordered():
    with pytest.raises(ValueError, match="must have hi > lo"):
        WatchlistPerformanceConfig(conviction_buckets=((50, 40),))


def test_extra_keys_forbidden():
    with pytest.raises(ValueError):
        WatchlistPerformanceConfig.from_dict({"nope": 1})
