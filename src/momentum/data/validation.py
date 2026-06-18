"""Data-quality gates for OHLCV bars.

Cheap, composable checks that turn "looks fine" into an auditable verdict before
bars reach the strategy. Each ``find_*`` helper returns the offending rows; the
:func:`validate_bars` aggregator rolls them into a :class:`BarQualityReport`,
optionally raising :class:`DataValidationError`.

The checks guard against the classic silent killers: duplicate timestamps,
non-positive prices, OHLC that can't be a real bar (e.g. ``high < low``),
implausible single-bar jumps, and (for daily data) missing trading sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from momentum.core.exceptions import DataValidationError
from momentum.data.schema import REQUIRED_COLUMNS, Timeframe, validate_schema


@dataclass(slots=True)
class BarQualityReport:
    """The outcome of validating one symbol's bar series."""

    symbol: str
    n_rows: int
    issues: list[str] = field(default_factory=list)
    duplicates: int = 0
    non_positive: int = 0
    ohlc_inconsistencies: int = 0
    spikes: int = 0
    gaps: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def __str__(self) -> str:
        status = "OK" if self.ok else "FAIL"
        detail = "; ".join(self.issues) if self.issues else "no issues"
        return f"<{self.symbol} {status} rows={self.n_rows} {detail}>"


def find_duplicates(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Timestamps appearing more than once in the index."""
    mask = df.index.duplicated(keep=False)
    return df.index[mask].unique()


def find_non_positive(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with a non-positive price or a negative volume."""
    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    bad = (df[price_cols] <= 0).any(axis=1)
    if "volume" in df.columns:
        bad = bad | (df["volume"] < 0)
    return df[bad]


def find_ohlc_inconsistencies(df: pd.DataFrame) -> pd.DataFrame:
    """Rows where the high/low envelope is impossible.

    A valid bar satisfies ``high >= max(open, close)`` and
    ``low <= min(open, close)`` and ``high >= low``.
    """
    needed = {"open", "high", "low", "close"}
    if not needed.issubset(df.columns):
        return df.iloc[:0]
    oc_max = df[["open", "close"]].max(axis=1)
    oc_min = df[["open", "close"]].min(axis=1)
    bad = (df["high"] < df["low"]) | (df["high"] < oc_max) | (df["low"] > oc_min)
    return df[bad]


def find_spikes(df: pd.DataFrame, *, threshold: float = 0.5) -> pd.DataFrame:
    """Rows whose close-to-close return exceeds ``threshold`` in magnitude.

    A 0.5 default flags >50% single-bar moves — almost always an unadjusted
    split or a bad print rather than a real day.
    """
    if "close" not in df.columns or len(df) < 2:
        return df.iloc[:0]
    returns = df["close"].pct_change()
    bad = returns.abs() > threshold
    bad = bad.fillna(False)
    return df[bad]


def find_session_gaps(df: pd.DataFrame, calendar: "object | None" = None) -> pd.DatetimeIndex:
    """Expected daily sessions missing from the index.

    If a ``calendar`` with a ``sessions(start, end)`` method is supplied it is
    used; otherwise a business-day (Mon–Fri) approximation is applied, which
    over-reports around holidays but never misses a real gap.
    """
    if df.empty:
        return pd.DatetimeIndex([], tz="UTC")
    start, end = df.index[0], df.index[-1]
    if calendar is not None and hasattr(calendar, "sessions"):
        expected = calendar.sessions(start, end)
    else:
        expected = pd.bdate_range(
            start.tz_convert(None).normalize(),
            end.tz_convert(None).normalize(),
        ).tz_localize("UTC")
    have = df.index.normalize()
    missing = expected.difference(have)
    return missing


def validate_bars(
    df: pd.DataFrame,
    symbol: str = "?",
    *,
    timeframe: Timeframe = Timeframe.DAY,
    spike_threshold: float = 0.5,
    check_gaps: bool = False,
    calendar: object | None = None,
    raise_on_error: bool = False,
) -> BarQualityReport:
    """Run every gate and summarize the result.

    Args:
        check_gaps: only meaningful for daily data; off by default because
            intraday/holiday calendars produce noisy gap counts.
        raise_on_error: raise :class:`DataValidationError` if any issue is found.
    """
    validate_schema(df)
    report = BarQualityReport(symbol=symbol, n_rows=len(df))
    if df.empty:
        return report

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        report.issues.append(f"missing columns {missing_cols}")

    dupes = find_duplicates(df)
    if len(dupes):
        report.duplicates = len(dupes)
        report.issues.append(f"{len(dupes)} duplicate timestamp(s)")

    nonpos = find_non_positive(df)
    if len(nonpos):
        report.non_positive = len(nonpos)
        report.issues.append(f"{len(nonpos)} non-positive price/volume row(s)")

    bad_ohlc = find_ohlc_inconsistencies(df)
    if len(bad_ohlc):
        report.ohlc_inconsistencies = len(bad_ohlc)
        report.issues.append(f"{len(bad_ohlc)} OHLC-inconsistent row(s)")

    spikes = find_spikes(df, threshold=spike_threshold)
    if len(spikes):
        report.spikes = len(spikes)
        report.issues.append(f"{len(spikes)} price spike(s) > {spike_threshold:.0%}")

    if check_gaps and timeframe is Timeframe.DAY:
        gaps = find_session_gaps(df, calendar)
        if len(gaps):
            report.gaps = len(gaps)
            report.issues.append(f"{len(gaps)} missing session(s)")

    if raise_on_error and not report.ok:
        raise DataValidationError(f"{symbol}: " + "; ".join(report.issues))
    return report


def has_lookahead(df: pd.DataFrame, as_of: pd.Timestamp) -> bool:
    """True if any bar is timestamped after ``as_of`` (a look-ahead guard)."""
    if df.empty:
        return False
    return bool((df.index > as_of).any())


__all__ = [
    "BarQualityReport",
    "find_duplicates",
    "find_non_positive",
    "find_ohlc_inconsistencies",
    "find_spikes",
    "find_session_gaps",
    "validate_bars",
    "has_lookahead",
]
