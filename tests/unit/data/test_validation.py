"""Tests for the data-quality gates."""

from __future__ import annotations

import pandas as pd

from momentum.data.schema import Timeframe
from momentum.data.validation import (
    find_non_positive,
    find_ohlc_inconsistencies,
    find_spikes,
    has_lookahead,
    validate_bars,
)


def test_clean_bars_pass(make_bars) -> None:
    report = validate_bars(make_bars(10), "AAPL")
    assert report.ok
    assert report.n_rows == 10
    assert "OK" in str(report)


def test_non_positive_detected(make_bars) -> None:
    bars = make_bars(5)
    bars.iloc[2, bars.columns.get_loc("close")] = -1.0
    found = find_non_positive(bars)
    assert len(found) == 1
    report = validate_bars(bars, "AAPL")
    assert not report.ok and report.non_positive == 1


def test_ohlc_inconsistency_detected(make_bars) -> None:
    bars = make_bars(5)
    # force high below low
    bars.iloc[1, bars.columns.get_loc("high")] = 0.0
    found = find_ohlc_inconsistencies(bars)
    assert len(found) >= 1


def test_spike_detected(make_bars) -> None:
    bars = make_bars(5, base=100.0)
    bars.iloc[3, bars.columns.get_loc("close")] = 1000.0  # ~9x jump
    found = find_spikes(bars, threshold=0.5)
    assert len(found) >= 1


def test_duplicates_detected() -> None:
    idx = pd.to_datetime(["2023-01-02", "2023-01-02", "2023-01-03"], utc=True)
    raw = pd.DataFrame(
        {
            "open": [1, 1, 1],
            "high": [2, 2, 2],
            "low": [0.5, 0.5, 0.5],
            "close": [1.5, 1.5, 1.5],
            "volume": [10, 10, 10],
        },
        index=idx,
    )
    raw.index.name = "timestamp"
    # bypass normalize's dedup to exercise the duplicate gate directly
    report = _validate_with_dupes(raw)
    assert report.duplicates >= 1


def _validate_with_dupes(raw: pd.DataFrame):
    from momentum.data.validation import find_duplicates

    # validate_bars requires schema; construct a report-equivalent assertion
    dupes = find_duplicates(raw)
    assert len(dupes) == 1
    from momentum.data.validation import BarQualityReport

    return BarQualityReport(symbol="X", n_rows=len(raw), duplicates=len(dupes))


def test_raise_on_error(make_bars) -> None:
    import pytest

    from momentum.core.exceptions import DataValidationError

    bars = make_bars(5)
    bars.iloc[0, bars.columns.get_loc("close")] = -5.0
    with pytest.raises(DataValidationError):
        validate_bars(bars, "AAPL", raise_on_error=True)


def test_gap_check_daily(make_bars) -> None:
    # weekdays Jan 2 (Mon) .. Jan 6 (Fri), drop Jan 4 (Wed)
    bars = make_bars(5, start="2023-01-02")
    bars = bars.drop(bars.index[2])
    report = validate_bars(bars, "AAPL", timeframe=Timeframe.DAY, check_gaps=True)
    assert report.gaps >= 1


def test_lookahead_guard(make_bars) -> None:
    bars = make_bars(5, start="2023-01-02")
    as_of = pd.Timestamp("2023-01-04", tz="UTC")
    assert has_lookahead(bars, as_of) is True
    assert has_lookahead(bars.loc[:as_of], as_of) is False


def test_empty_frame_is_ok() -> None:
    from momentum.data.schema import empty_bars

    report = validate_bars(empty_bars(extended=True), "X")
    assert report.ok and report.n_rows == 0
