"""Volatility estimation — the unit of risk.

Everything in the engine scales off a volatility estimate so positions in calm
and wild names carry comparable risk. ATR (Wilder) drives stops and
risk-per-share; close-to-close / EWMA σ drives volatility targeting and exposure
scaling.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from momentum.core.constants import TRADING_DAYS_PER_YEAR
from momentum.signals.indicators import atr as _atr_series

__all__ = ["atr", "realized_volatility", "ewma_volatility", "annualize"]


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> float:
    """Latest Wilder ATR over ``period`` bars (NaN if insufficient history)."""
    series = _atr_series(high, low, close, period)
    value = series.iloc[-1] if len(series) else np.nan
    return float(value)


def annualize(daily_sigma: float, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Scale a per-period σ to annual via the √time rule."""
    return float(float(daily_sigma) * np.sqrt(periods_per_year))


def realized_volatility(close: pd.Series, window: int = 20, *, annualized: bool = True) -> float:
    """Close-to-close realized volatility from the last ``window`` returns."""
    returns = close.pct_change().dropna()
    if len(returns) < 2:
        return float("nan")
    sigma = float(returns.tail(window).std(ddof=1))
    return annualize(sigma) if annualized else sigma


def ewma_volatility(close: pd.Series, span: int = 20, *, annualized: bool = True) -> float:
    """Exponentially-weighted volatility — more responsive to recent moves."""
    returns = close.pct_change().dropna()
    if len(returns) < 2:
        return float("nan")
    sigma = float(returns.ewm(span=span, adjust=False).std(bias=False).iloc[-1])
    return annualize(sigma) if annualized else sigma
