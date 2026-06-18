"""OHLCV bar helpers: resampling, alignment and rolling-window assembly.

Pure pandas transforms over the canonical bar contract. Nothing here touches a
vendor or the cache — these are the building blocks signals/universe code uses
to reshape clean bars (e.g. daily -> weekly, or many symbols into one aligned
panel for cross-sectional ranking).
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from momentum.data.schema import (
    OPTIONAL_COLUMNS,
    Timeframe,
    empty_bars,
    normalize_bars,
)

# How each canonical column collapses when down-sampling a window of bars.
_AGG_RULES: dict[str, str] = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "trade_count": "sum",
    "vwap": "mean",
}


def resample(df: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """Down-sample bars to a coarser ``timeframe`` (e.g. daily -> weekly).

    Empty buckets (no underlying bars) are dropped, so the result has no
    all-NaN rows.
    """
    df = normalize_bars(df)
    if df.empty:
        return df
    agg = {c: _AGG_RULES[c] for c in df.columns if c in _AGG_RULES}
    out = df.resample(timeframe.pandas_freq).agg(agg)
    out = out.dropna(subset=["open", "high", "low", "close"], how="all")
    return normalize_bars(out)


def align(frames: Mapping[str, pd.DataFrame], *, how: str = "outer") -> dict[str, pd.DataFrame]:
    """Reindex several symbols onto a shared timestamp axis.

    With ``how="outer"`` every symbol is reindexed to the union of all
    timestamps (missing bars become NaN); ``how="inner"`` keeps only timestamps
    present in *every* symbol. The keys/order of ``frames`` are preserved.
    """
    normalized = {s: normalize_bars(f) for s, f in frames.items()}
    if not normalized:
        return {}
    indexes = [f.index for f in normalized.values() if not f.empty]
    if not indexes:
        return normalized
    axis = indexes[0]
    for idx in indexes[1:]:
        axis = axis.union(idx) if how == "outer" else axis.intersection(idx)
    axis = axis.sort_values()
    return {s: f.reindex(axis) for s, f in normalized.items()}


def to_panel(frames: Mapping[str, pd.DataFrame], field: str = "close") -> pd.DataFrame:
    """A wide ``timestamp x symbol`` frame of a single ``field`` (e.g. close).

    Ideal for cross-sectional work: correlations, ranking, breadth.
    """
    aligned = align(frames, how="outer")
    if not aligned:
        return pd.DataFrame()
    data = {s: f[field] for s, f in aligned.items() if field in f.columns}
    panel = pd.DataFrame(data)
    panel.index.name = "timestamp"
    return panel


def combine(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack per-symbol frames into one ``(symbol, timestamp)`` MultiIndex frame."""
    parts = []
    for symbol, frame in frames.items():
        f = normalize_bars(frame).copy()
        f["symbol"] = symbol.upper()
        parts.append(f.set_index("symbol", append=True))
    if not parts:
        return empty_bars(extended=True)
    out = pd.concat(parts).reorder_levels(["symbol", "timestamp"]).sort_index()
    return out


def rolling_window(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """The most recent ``lookback`` bars (point-in-time slice helper)."""
    df = normalize_bars(df)
    if lookback <= 0:
        return df.iloc[0:0]
    return df.iloc[-lookback:]


def latest_bar(df: pd.DataFrame) -> pd.Series | None:
    """The final bar as a Series, or ``None`` if the frame is empty."""
    df = normalize_bars(df)
    if df.empty:
        return None
    return df.iloc[-1]


def drop_optional(df: pd.DataFrame) -> pd.DataFrame:
    """Return just the core OHLCV columns (drop trade_count/vwap if present)."""
    return df.drop(columns=[c for c in OPTIONAL_COLUMNS if c in df.columns])
