"""Cheap liquidity prefilter — keep huge universes responsive.

"All Tradable Stocks" can be 5000+ symbols. Fully featurising and scoring every
one each scan is wasteful when most are illiquid and would be filtered out anyway.
This module applies a **cheap** pre-pass (last price floor + recent dollar-volume,
no indicators) and caps the set to the most liquid ``max_symbols`` before the full
scan. The full scanner then runs on the reduced set with its normal filters.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


def liquidity_prefilter(
    bars: Mapping[str, pd.DataFrame],
    *,
    min_price: float = 0.0,
    min_dollar_volume: float = 0.0,
    max_symbols: int | None = None,
    lookback: int = 20,
) -> list[str]:
    """Symbols to fully scan: liquid enough, capped to the top ``max_symbols``.

    Ranks by recent average dollar volume (price · volume over ``lookback`` bars)
    and returns the survivors, most-liquid first. Pure + cheap (no indicators).
    """
    scored: list[tuple[str, float]] = []
    for symbol, frame in bars.items():
        if frame is None or frame.empty or "close" not in frame.columns:
            continue
        close = frame["close"].dropna()
        if close.empty:
            continue
        price = float(close.iloc[-1])
        if price < min_price:
            continue
        if "volume" in frame.columns:
            tail_close = close.tail(lookback)
            tail_vol = frame["volume"].reindex(tail_close.index)
            adv = float((tail_close * tail_vol).mean(skipna=True))
        else:
            adv = 0.0
        if adv < min_dollar_volume:
            continue
        scored.append((symbol, adv))

    scored.sort(key=lambda item: item[1], reverse=True)
    if max_symbols is not None and len(scored) > max_symbols:
        scored = scored[:max_symbols]
    return [symbol for symbol, _ in scored]
