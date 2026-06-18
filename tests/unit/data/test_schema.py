"""Tests for the canonical OHLCV schema and helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from momentum.core.exceptions import SchemaError
from momentum.data.schema import (
    REQUIRED_COLUMNS,
    Adjustment,
    Timeframe,
    empty_bars,
    normalize_bars,
    to_utc_timestamp,
    validate_schema,
)


class TestTimeframe:
    def test_vendor_translations(self) -> None:
        assert Timeframe.DAY.alpaca == "1Day"
        assert Timeframe.DAY.polygon == (1, "day")
        assert Timeframe.MINUTE.yahoo == "1m"
        assert Timeframe.WEEK.pandas_freq == "W"

    @pytest.mark.parametrize(
        "token,expected",
        [("1Day", Timeframe.DAY), ("DAY", Timeframe.DAY), ("1Min", Timeframe.MINUTE)],
    )
    def test_parse(self, token: str, expected: Timeframe) -> None:
        assert Timeframe.parse(token) is expected

    def test_parse_passthrough_and_error(self) -> None:
        assert Timeframe.parse(Timeframe.HOUR) is Timeframe.HOUR
        with pytest.raises(SchemaError):
            Timeframe.parse("fortnight")


class TestAdjustment:
    def test_flags(self) -> None:
        assert Adjustment.ALL.includes_splits and Adjustment.ALL.includes_dividends
        assert Adjustment.SPLIT.includes_splits
        assert not Adjustment.SPLIT.includes_dividends
        assert not Adjustment.RAW.includes_splits


class TestToUtcTimestamp:
    def test_naive_assumed_utc(self) -> None:
        ts = to_utc_timestamp("2023-01-02")
        assert ts.tz is not None
        assert str(ts.tz) == "UTC"

    def test_tz_aware_converted(self) -> None:
        ts = to_utc_timestamp(pd.Timestamp("2023-01-02 12:00", tz="America/New_York"))
        assert ts.hour == 17  # EST is UTC-5


class TestNormalizeBars:
    def test_empty(self) -> None:
        df = empty_bars(extended=True)
        validate_schema(df)
        assert list(df.columns)[: len(REQUIRED_COLUMNS)] == list(REQUIRED_COLUMNS)

    def test_sorts_and_dedups_keep_last(self) -> None:
        idx = pd.to_datetime(["2023-01-03", "2023-01-02", "2023-01-03"], utc=True)
        raw = pd.DataFrame(
            {
                "open": [1, 2, 9],
                "high": [1, 2, 9],
                "low": [1, 2, 9],
                "close": [1, 2, 9],
                "volume": [1, 2, 9],
            },
            index=idx,
        )
        out = normalize_bars(raw)
        assert out.index.is_monotonic_increasing
        assert not out.index.has_duplicates
        # last duplicate (close=9) wins
        assert out.loc[out.index[-1], "close"] == 9.0

    def test_localizes_naive_index(self) -> None:
        idx = pd.date_range("2023-01-02", periods=3, freq="D")  # naive
        raw = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in REQUIRED_COLUMNS}, index=idx)
        out = normalize_bars(raw)
        assert out.index.tz is not None

    def test_missing_column_raises(self) -> None:
        raw = pd.DataFrame({"open": [1.0], "high": [1.0]})
        with pytest.raises(SchemaError):
            normalize_bars(raw)

    def test_idempotent(self) -> None:
        idx = pd.date_range("2023-01-02", periods=3, freq="D", tz="UTC")
        raw = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in REQUIRED_COLUMNS}, index=idx)
        once = normalize_bars(raw)
        twice = normalize_bars(once)
        pd.testing.assert_frame_equal(once, twice)


class TestValidateSchema:
    def test_rejects_naive_index(self) -> None:
        idx = pd.date_range("2023-01-02", periods=2, freq="D")  # naive
        df = pd.DataFrame({c: [1.0, 2.0] for c in REQUIRED_COLUMNS}, index=idx)
        df.index.name = "timestamp"
        with pytest.raises(SchemaError):
            validate_schema(df)
