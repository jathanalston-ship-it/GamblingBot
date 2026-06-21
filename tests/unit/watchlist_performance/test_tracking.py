"""Tests for the pure forward-performance tracking."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from momentum.watchlist_performance import (
    EntryPrediction,
    compute_forward,
    default_config,
    track_entry,
)

CFG = default_config()


def _pred(as_of: dt.date) -> EntryPrediction:
    return EntryPrediction(
        run_id="r",
        as_of=as_of,
        horizon="monthly",
        horizon_label="This Month",
        symbol="AAA",
        conviction=80.0,
        rank=1,
        expected_move_pct=0.08,
        horizon_days=21,
    )


def test_compute_forward_returns_and_excursions():
    ref = 100.0
    closes = [101.0, 102.0, 103.0, 104.0, 105.0] + [106.0] * 16  # 21 bars
    highs = [c + 2 for c in closes]
    lows = [c - 3 for c in closes]
    perf = compute_forward(ref, closes, highs, lows, CFG)
    assert perf.ret_1d == 101.0 / 100.0 - 1.0
    assert perf.ret_1w == 105.0 / 100.0 - 1.0  # 5th bar
    assert perf.ret_1m == 106.0 / 100.0 - 1.0  # 21st bar
    assert perf.mfe == max(highs) / ref - 1.0
    assert perf.mae == min(lows) / ref - 1.0
    assert perf.bars_tracked == 21
    assert perf.complete is True


def test_compute_forward_incomplete_window():
    ref = 100.0
    closes = [101.0, 102.0, 103.0]  # only 3 forward bars
    perf = compute_forward(ref, closes, closes, closes, CFG)
    assert perf.ret_1d is not None
    assert perf.ret_1w is None  # < 5 bars
    assert perf.ret_1m is None  # < 21 bars
    assert perf.bars_tracked == 3
    assert perf.complete is False


def test_track_entry_uses_close_on_as_of_as_reference():
    as_of = dt.date(2024, 1, 15)
    idx = pd.date_range("2024-01-10", periods=40, freq="B", tz="UTC")
    close = np.linspace(100.0, 139.0, 40)
    bars = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e6},
        index=idx,
    )
    rec = track_entry(_pred(as_of), bars, CFG)
    assert rec is not None
    on_as_of = bars[bars.index.date <= as_of]["close"].iloc[-1]
    assert rec.reference_price == float(on_as_of)
    assert rec.ret_1m is not None and rec.ret_1m > 0  # rising series
    assert rec.mae is not None and rec.mae <= rec.mfe


def test_track_entry_none_when_no_reference_bar():
    as_of = dt.date(2024, 1, 15)
    # bars entirely after as_of => no reference price available
    idx = pd.date_range("2024-02-01", periods=10, freq="B", tz="UTC")
    bars = pd.DataFrame({"close": np.arange(10.0)}, index=idx)
    assert track_entry(_pred(as_of), bars, CFG) is None
