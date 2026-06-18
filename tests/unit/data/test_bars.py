"""Tests for OHLCV bar helpers (resample/align/panel/combine)."""

from __future__ import annotations


from momentum.data.bars import (
    align,
    combine,
    drop_optional,
    latest_bar,
    resample,
    rolling_window,
    to_panel,
)
from momentum.data.schema import Timeframe


def test_resample_daily_to_weekly(make_bars) -> None:
    bars = make_bars(10, start="2023-01-02")  # two work-ish weeks
    weekly = resample(bars, Timeframe.WEEK)
    assert len(weekly) < len(bars)
    # weekly open == first daily open of the bucket, high == max
    assert weekly["high"].iloc[0] == bars["high"].iloc[:7].max()


def test_resample_aggregation_rules(make_bars) -> None:
    bars = make_bars(7, start="2023-01-02")
    weekly = resample(bars, Timeframe.WEEK)
    first_week = weekly.iloc[0]
    assert first_week["open"] == bars["open"].iloc[0]
    assert first_week["volume"] == bars["volume"].iloc[:7].sum()


def test_align_outer_union(make_bars) -> None:
    a = make_bars(5, start="2023-01-02")
    b = make_bars(5, start="2023-01-04")
    aligned = align({"A": a, "B": b}, how="outer")
    # union spans 2023-01-02 .. 2023-01-08 => 7 days
    assert len(aligned["A"]) == 7
    assert aligned["A"].isna().any().any()  # A has NaN where only B exists


def test_align_inner_intersection(make_bars) -> None:
    a = make_bars(5, start="2023-01-02")
    b = make_bars(5, start="2023-01-04")
    aligned = align({"A": a, "B": b}, how="inner")
    assert len(aligned["A"]) == 3  # overlap 01-04..01-06


def test_to_panel(make_bars) -> None:
    a = make_bars(3, start="2023-01-02", base=100.0)
    b = make_bars(3, start="2023-01-02", base=200.0)
    panel = to_panel({"A": a, "B": b}, field="close")
    assert list(panel.columns) == ["A", "B"]
    assert panel["B"].iloc[0] == 200.0


def test_combine_multiindex(make_bars) -> None:
    a = make_bars(2, start="2023-01-02")
    b = make_bars(2, start="2023-01-02")
    stacked = combine({"AAPL": a, "MSFT": b})
    assert stacked.index.names == ["symbol", "timestamp"]
    assert set(stacked.index.get_level_values("symbol")) == {"AAPL", "MSFT"}


def test_rolling_window(make_bars) -> None:
    bars = make_bars(10)
    assert len(rolling_window(bars, 3)) == 3
    assert rolling_window(bars, 0).empty


def test_latest_bar(make_bars) -> None:
    bars = make_bars(5)
    last = latest_bar(bars)
    assert last is not None
    assert last["close"] == bars["close"].iloc[-1]
    from momentum.data.schema import empty_bars

    assert latest_bar(empty_bars()) is None


def test_drop_optional(make_bars) -> None:
    bars = make_bars(3, extended=True)
    core = drop_optional(bars)
    assert "vwap" not in core.columns
    assert "trade_count" not in core.columns
    assert "close" in core.columns
