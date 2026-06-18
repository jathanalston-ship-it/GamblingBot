"""Momentum measurement & cross-sectional ranking.

Two halves:

* **Time-series momentum** for a single symbol — blended rate-of-change over
  several lookbacks (e.g. 3/6/12-month), optionally "skipping" the most recent
  month to dodge short-term mean reversion (the classic 12-1 construction).
* **Cross-sectional tools** that rank a *panel* of symbols against each other —
  percentile ranks and z-scores — which is how the scanner turns raw features
  into a comparable 0..100 momentum score.

All functions are pure; the scanner composes them.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from momentum.signals.indicators import roc


def blended_momentum(
    close: pd.Series,
    lookbacks: Mapping[int, float],
    *,
    skip: int = 0,
) -> float | None:
    """Weighted blend of trailing returns over several ``lookbacks`` (in bars).

    ``lookbacks`` maps period -> weight. ``skip`` excludes the most recent
    ``skip`` bars from every window (12-1 momentum uses ``skip≈21``). Returns the
    latest blended value as a fraction, or ``None`` if there is too little data.
    """
    if close.empty:
        return None
    ref = close.shift(skip) if skip else close
    total_w = 0.0
    acc = 0.0
    for period, weight in lookbacks.items():
        if len(ref.dropna()) <= period:
            continue
        change = roc(ref, period).iloc[-1]
        if pd.isna(change):
            continue
        acc += float(change) * weight
        total_w += weight
    if total_w == 0:
        return None
    return acc / total_w


def percentile_rank(values: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank in ``[0, 1]`` (NaNs stay NaN).

    The best (largest) value ranks ~1.0, the worst ~0.0; ties share their
    average rank.
    """
    return values.rank(pct=True, na_option="keep")


def zscore(values: pd.Series) -> pd.Series:
    """Cross-sectional z-score; constant input yields all-zeros."""
    std = values.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=values.index).where(values.notna())
    return (values - values.mean()) / std


def relative_strength(values: pd.Series, benchmark: float) -> pd.Series:
    """Each value relative to a benchmark scalar (ratio, 1.0 == in line)."""
    if benchmark == 0:
        return pd.Series(np.nan, index=values.index)
    return values / benchmark


def sector_relative_strength(momentum: pd.Series, sectors: pd.Series) -> pd.Series:
    """Mean momentum percentile of each symbol's sector.

    ``momentum`` is a per-symbol momentum measure; ``sectors`` maps the same
    index to a sector label. Each symbol receives its *sector's* average
    percentile rank (0.5 == an average sector), so symbols in collectively
    strong sectors score high regardless of their own rank.
    """
    pr = percentile_rank(momentum)
    frame = pd.DataFrame({"pr": pr, "sector": sectors})
    sector_means = frame.groupby("sector")["pr"].transform("mean")
    return sector_means.reindex(momentum.index)
