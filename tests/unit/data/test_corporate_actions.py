"""Tests for split/dividend back-adjustment."""

from __future__ import annotations

import pandas as pd

from momentum.data.corporate_actions import (
    adjust,
    adjust_for_splits,
    dividend_factors,
    split_factors,
)
from momentum.data.schema import normalize_bars


def _bars(closes: list[float], start: str = "2023-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return normalize_bars(df)


def _actions(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    idx = pd.to_datetime([r[0] for r in rows], utc=True)
    df = pd.DataFrame({"action": [r[1] for r in rows], "value": [r[2] for r in rows]}, index=idx)
    df.index.name = "timestamp"
    return df.sort_index()


def test_split_factor_halves_pre_split_prices() -> None:
    bars = _bars([100, 100, 100, 100], start="2023-01-02")  # split ex on 01-04
    actions = _actions([("2023-01-04", "split", 2.0)])
    factor = split_factors(bars, actions)
    # bars before 01-04 get factor 2.0; on/after get 1.0
    assert factor.iloc[0] == 2.0
    assert factor.iloc[-1] == 1.0


def test_adjust_for_splits_prices_and_volume() -> None:
    bars = _bars([100, 100, 50, 50], start="2023-01-02")  # raw shows the drop
    actions = _actions([("2023-01-04", "split", 2.0)])
    adjusted = adjust_for_splits(bars, actions)
    # pre-split 100 -> 50 (divided by 2), making the series continuous
    assert adjusted["close"].iloc[0] == 50.0
    assert adjusted["close"].iloc[-1] == 50.0
    # volume scaled up
    assert adjusted["volume"].iloc[0] == 2000.0


def test_dividend_factor_below_one() -> None:
    bars = _bars([100, 100, 100], start="2023-01-02")
    actions = _actions([("2023-01-04", "dividend", 1.0)])  # $1 div, close 100 -> ratio .99
    factor = dividend_factors(bars, actions)
    assert factor.iloc[0] == 0.99
    assert factor.iloc[-1] == 1.0


def test_adjust_combined_noop_when_no_actions() -> None:
    bars = _bars([10, 11, 12])
    empty = _actions([])
    out = adjust(bars, empty)
    pd.testing.assert_frame_equal(out, bars)


def test_adjust_applies_both() -> None:
    bars = _bars([100, 100, 50, 50], start="2023-01-02")
    actions = _actions([("2023-01-04", "split", 2.0), ("2023-01-04", "dividend", 0.5)])
    out = adjust(bars, actions)
    # split makes it continuous at 50; dividend nudges earlier bars slightly lower
    assert out["close"].iloc[-1] == 50.0
    assert out["close"].iloc[0] < 50.0
