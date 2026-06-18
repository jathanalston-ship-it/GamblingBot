"""Return-stream metrics computed from an equity curve.

Pure functions over a pandas equity series (or its returns): CAGR, volatility,
Sharpe, Sortino, Calmar, total return and the return tail ratio. These describe
*how* the equity was earned; the trade-level objective metrics live in
:mod:`momentum.analytics.trade_analysis`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from momentum.analytics.drawdown_analysis import max_drawdown
from momentum.core.constants import EPS, TRADING_DAYS_PER_YEAR

__all__ = [
    "to_returns",
    "total_return",
    "cagr",
    "annual_volatility",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "return_tail_ratio",
]


def to_returns(equity: pd.Series) -> pd.Series:
    """Periodic simple returns of an equity curve."""
    return equity.pct_change().dropna()


def total_return(equity: pd.Series) -> float:
    """Cumulative return over the whole curve."""
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def cagr(equity: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Compound annual growth rate implied by the curve's length."""
    n = len(equity)
    if n < 2 or equity.iloc[0] <= 0:
        return 0.0
    years = (n - 1) / periods_per_year
    if years <= 0:
        return 0.0
    growth = equity.iloc[-1] / equity.iloc[0]
    if growth <= 0:
        return -1.0
    return float(growth ** (1.0 / years) - 1.0)


def annual_volatility(equity: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualized volatility of periodic returns."""
    returns = to_returns(equity)
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(
    equity: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualized Sharpe ratio (excess return per unit of total volatility)."""
    returns = to_returns(equity)
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    std = excess.std(ddof=1)
    if std <= EPS:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(
    equity: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualized Sortino ratio — penalizes only downside deviation.

    Apt for a positive-skew strategy: upside volatility (large winners) should
    not be charged as "risk".
    """
    returns = to_returns(equity)
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    downside = excess[excess < 0]
    if downside.size == 0:
        return float("inf") if excess.mean() > 0 else 0.0
    downside_dev = np.sqrt((downside**2).mean())
    if downside_dev <= EPS:
        return 0.0
    return float(excess.mean() / downside_dev * np.sqrt(periods_per_year))


def calmar_ratio(equity: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """CAGR divided by maximum drawdown magnitude."""
    mdd = abs(max_drawdown(equity))
    if mdd <= EPS:
        return 0.0
    return cagr(equity, periods_per_year) / mdd


def return_tail_ratio(equity: pd.Series, q: float = 0.05) -> float:
    """Right/left tail ratio of periodic returns (positive-skew check)."""
    returns = to_returns(equity)
    if len(returns) < 2:
        return 0.0
    hi = float(np.quantile(returns, 1.0 - q))
    lo = float(np.quantile(returns, q))
    return abs(hi) / abs(lo) if abs(lo) > EPS else 0.0
