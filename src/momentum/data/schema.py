"""The canonical OHLCV contract shared by every data-layer component.

One schema, enforced once (:func:`normalize_bars`), trusted everywhere. A
"bars" DataFrame is:

* indexed by a tz-aware (UTC) ``DatetimeIndex`` named ``timestamp``,
  sorted ascending and unique;
* columns ``open, high, low, close, volume`` (required) plus optional
  ``trade_count, vwap``, in that order;
* floating-point dtypes throughout (NaN-safe; efficient in parquet).

Providers translate their vendor payloads into this shape; the cache, the
validators, ingestion and everything downstream consume it. Keeping the
contract in one place is what lets the three vendors be interchangeable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from momentum.core.exceptions import SchemaError

INDEX_NAME = "timestamp"
REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
OPTIONAL_COLUMNS: tuple[str, ...] = ("trade_count", "vwap")
ALL_COLUMNS: tuple[str, ...] = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

# Corporate-actions frame: indexed by ``timestamp`` (ex-date), one row per event.
CA_COLUMNS: tuple[str, ...] = ("action", "value")


class Timeframe(Enum):
    """Bar granularity, with per-vendor translations.

    The enum *value* is the canonical token used in cache paths and configs.
    """

    MINUTE = "1Min"
    HOUR = "1Hour"
    DAY = "1Day"
    WEEK = "1Week"

    @property
    def pandas_freq(self) -> str:
        """Offset alias for :meth:`pandas.DataFrame.resample`."""
        return {
            Timeframe.MINUTE: "min",
            Timeframe.HOUR: "h",
            Timeframe.DAY: "D",
            Timeframe.WEEK: "W",
        }[self]

    @property
    def alpaca(self) -> str:
        """Alpaca ``timeframe`` query value."""
        return self.value

    @property
    def polygon(self) -> tuple[int, str]:
        """Polygon ``(multiplier, timespan)`` pair."""
        return {
            Timeframe.MINUTE: (1, "minute"),
            Timeframe.HOUR: (1, "hour"),
            Timeframe.DAY: (1, "day"),
            Timeframe.WEEK: (1, "week"),
        }[self]

    @property
    def yahoo(self) -> str:
        """Yahoo ``interval`` query value."""
        return {
            Timeframe.MINUTE: "1m",
            Timeframe.HOUR: "1h",
            Timeframe.DAY: "1d",
            Timeframe.WEEK: "1wk",
        }[self]

    @classmethod
    def parse(cls, value: "str | Timeframe") -> "Timeframe":
        """Coerce a string (canonical token or enum name) into a Timeframe."""
        if isinstance(value, Timeframe):
            return value
        token = value.strip()
        for tf in cls:
            if token == tf.value or token.upper() == tf.name:
                return tf
        raise SchemaError(f"unknown timeframe: {value!r}")


class Adjustment(Enum):
    """How corporate actions are reflected in returned prices."""

    RAW = "raw"
    SPLIT = "split"
    DIVIDEND = "dividend"
    ALL = "all"

    @property
    def includes_dividends(self) -> bool:
        return self in (Adjustment.DIVIDEND, Adjustment.ALL)

    @property
    def includes_splits(self) -> bool:
        return self in (Adjustment.SPLIT, Adjustment.ALL)


@dataclass(frozen=True, slots=True)
class DataRequest:
    """An immutable description of a single bar download."""

    symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    timeframe: Timeframe = Timeframe.DAY
    adjustment: Adjustment = Adjustment.ALL
    extra: dict[str, object] = field(default_factory=dict)


def to_utc_timestamp(value: str | dt.date | dt.datetime | pd.Timestamp) -> pd.Timestamp:
    """Coerce any date-like value to a tz-aware UTC :class:`pandas.Timestamp`.

    Naive inputs and plain ``date`` objects are assumed to already be UTC.
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def empty_bars(*, extended: bool = False) -> pd.DataFrame:
    """An empty, correctly-typed canonical bars frame."""
    cols = list(ALL_COLUMNS if extended else REQUIRED_COLUMNS)
    idx = pd.DatetimeIndex([], tz="UTC", name=INDEX_NAME)
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols}, index=idx)


def normalize_bars(df: pd.DataFrame, *, keep_optional: bool = True) -> pd.DataFrame:
    """Coerce an arbitrary OHLCV frame into the canonical contract.

    Idempotent: re-normalizing a canonical frame returns an equivalent frame.
    Sorting and de-duplication (keep last) make the result safe to merge.

    Raises:
        SchemaError: if a required OHLCV column is missing.
    """
    if df.empty and not len(df.columns):
        return empty_bars(extended=keep_optional)

    out = df.copy()

    # --- index -> tz-aware UTC DatetimeIndex named "timestamp" ---------------
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    elif out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out.index.name = INDEX_NAME

    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise SchemaError(f"bars frame missing required columns: {missing}")

    cols = list(REQUIRED_COLUMNS)
    if keep_optional:
        cols += [c for c in OPTIONAL_COLUMNS if c in out.columns]
    out = out[cols].astype("float64")

    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    return out


def validate_schema(df: pd.DataFrame) -> None:
    """Assert a frame already satisfies the canonical contract (no copy).

    Raises:
        SchemaError: on any structural violation.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise SchemaError("index must be a DatetimeIndex")
    if df.index.tz is None:
        raise SchemaError("index must be tz-aware (UTC)")
    if df.index.name != INDEX_NAME:
        raise SchemaError(f"index must be named {INDEX_NAME!r}")
    if not df.index.is_monotonic_increasing:
        raise SchemaError("index must be sorted ascending")
    if df.index.has_duplicates:
        raise SchemaError("index must be unique")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"missing required columns: {missing}")
