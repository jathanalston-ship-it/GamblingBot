"""Split/dividend back-adjustment for continuous, point-in-time-correct prices.

When a provider only returns *raw* prices, these helpers fold a corporate-actions
series (from ``provider.get_corporate_actions``) into the bars so historical
prices line up with today's quoted price — the standard "back-adjust" used for
research and backtests.

Convention for the actions frame (see :data:`schema.CA_COLUMNS`): indexed by the
ex-date (UTC), with columns ``action`` ("split"|"dividend") and ``value``. For a
split, ``value`` is the ratio ``new/old`` (a 2-for-1 split is ``2.0``); for a
dividend, ``value`` is the cash amount per share.
"""

from __future__ import annotations

import pandas as pd

from momentum.data.schema import normalize_bars


def split_factors(df: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Cumulative split divisor to apply to each bar (1.0 = no adjustment).

    A bar *before* a 2-for-1 split is divided by 2 so it matches the post-split
    price scale. The factor is the product of all split ratios with ex-date
    strictly after the bar.
    """
    factor = pd.Series(1.0, index=df.index)
    splits = actions[actions["action"] == "split"]
    for ex_date, value in splits["value"].items():
        ratio = float(value)
        if ratio <= 0:
            continue
        factor.loc[df.index < ex_date] *= ratio
    return factor


def adjust_for_splits(df: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Back-adjust prices and volume for splits only."""
    df = normalize_bars(df)
    if df.empty or actions.empty:
        return df
    factor = split_factors(df, actions)
    out = df.copy()
    for col in ("open", "high", "low", "close", "vwap"):
        if col in out.columns:
            out[col] = out[col] / factor
    if "volume" in out.columns:
        out["volume"] = out["volume"] * factor
    return normalize_bars(out)


def dividend_factors(df: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Cumulative dividend-adjustment multiplier per bar (<= 1.0).

    Uses the standard CRSP-style ratio: on each ex-date the prior closes are
    scaled by ``1 - dividend/close_before``. The product of those factors gives
    the multiplier applied to every earlier bar.
    """
    factor = pd.Series(1.0, index=df.index)
    if "close" not in df.columns:
        return factor
    divs = actions[actions["action"] == "dividend"]
    for ex_date, amount in divs["value"].items():
        prior = df.index[df.index < ex_date]
        if prior.empty:
            continue
        close_before = float(df.loc[prior[-1], "close"])
        if close_before <= 0:
            continue
        ratio = 1.0 - float(amount) / close_before
        if ratio <= 0:
            continue
        factor.loc[df.index < ex_date] *= ratio
    return factor


def adjust(
    df: pd.DataFrame,
    actions: pd.DataFrame,
    *,
    splits: bool = True,
    dividends: bool = True,
) -> pd.DataFrame:
    """Fully back-adjust raw bars for splits and/or dividends."""
    out = normalize_bars(df)
    if out.empty or actions.empty:
        return out
    if splits:
        out = adjust_for_splits(out, actions)
    if dividends:
        factor = dividend_factors(out, actions)
        for col in ("open", "high", "low", "close", "vwap"):
            if col in out.columns:
                out[col] = out[col] * factor
    return normalize_bars(out)
