"""Correlation & clustering controls — real diversification, not nominal.

Ten correlated breakouts are one bet, not ten. A new entry whose return
correlation with an open position exceeds the limit is rejected, and the number
of positions in one correlated cluster is capped.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

__all__ = ["pairwise_correlation", "max_correlation_with_open", "correlated_cluster_size"]


def pairwise_correlation(a: pd.Series, b: pd.Series, *, min_overlap: int = 20) -> float | None:
    """Pearson correlation of two return series over their overlapping dates.

    Returns ``None`` when the overlap is too short to be meaningful.
    """
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(joined) < min_overlap:
        return None
    corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
    return None if pd.isna(corr) else float(corr)


def max_correlation_with_open(
    candidate: pd.Series | None,
    open_returns: Mapping[str, pd.Series],
    *,
    lookback: int = 60,
    min_overlap: int = 20,
) -> tuple[float | None, str | None]:
    """Largest correlation of ``candidate`` with any open position's returns.

    Returns ``(max_corr, symbol)`` — both ``None`` if it cannot be computed.
    """
    if candidate is None or candidate.empty or not open_returns:
        return None, None
    cand = candidate.tail(lookback)
    best: float | None = None
    best_symbol: str | None = None
    for symbol, series in open_returns.items():
        if series is None or series.empty:
            continue
        corr = pairwise_correlation(cand, series.tail(lookback), min_overlap=min_overlap)
        if corr is None:
            continue
        if best is None or corr > best:
            best, best_symbol = corr, symbol
    return best, best_symbol


def correlated_cluster_size(
    candidate: pd.Series | None,
    open_returns: Mapping[str, pd.Series],
    *,
    threshold: float,
    lookback: int = 60,
    min_overlap: int = 20,
) -> int:
    """How many open positions the candidate is correlated with above ``threshold``."""
    if candidate is None or candidate.empty:
        return 0
    cand = candidate.tail(lookback)
    count = 0
    for series in open_returns.values():
        if series is None or series.empty:
            continue
        corr = pairwise_correlation(cand, series.tail(lookback), min_overlap=min_overlap)
        if corr is not None and corr >= threshold:
            count += 1
    return count
