"""Account mathematics — pure functions from raw account facts to metrics.

Nothing here touches the database: the venue hands in the primitives (cash
split, open positions, closed-trade results, the equity history) and gets the
full account picture back. Settlement is modeled explicitly: sale proceeds
are **unsettled** for ``settlement_days`` business days and only settled cash
counts toward buying power.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from momentum.analytics.statistics import expectancy, safe_divide


@dataclass(frozen=True, slots=True)
class PendingSettlement:
    """Sale proceeds waiting out the T+n settlement window."""

    amount: float
    settles_at: dt.datetime

    def to_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "settles_at": self.settles_at.isoformat()}


def split_settled(
    cash: float, pending: list[PendingSettlement], now: dt.datetime
) -> tuple[float, float, list[PendingSettlement]]:
    """Split total cash into (settled, unsettled) and drop matured holds."""
    still_pending = [p for p in pending if p.settles_at > now]
    unsettled = sum(p.amount for p in still_pending)
    return cash - unsettled, unsettled, still_pending


def settlement_time(ts: dt.datetime, settlement_days: int) -> dt.datetime:
    """When a sale's proceeds settle: T+n business days at the same time."""
    settle = ts
    remaining = settlement_days
    while remaining > 0:
        settle += dt.timedelta(days=1)
        if settle.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return settle


def max_drawdown(equity: list[float]) -> float:
    """Deepest peak-to-trough decline as a fraction (0.12 = -12%)."""
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def sharpe_ratio(equity: list[float], *, periods_per_year: int = 252) -> float | None:
    """Annualized Sharpe from the equity curve's period returns (rf = 0)."""
    if len(equity) < 3:
        return None
    returns = [(b - a) / a for a, b in zip(equity[:-1], equity[1:], strict=True) if a > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return None
    return mean / std * math.sqrt(periods_per_year)


@dataclass(frozen=True, slots=True)
class AccountMetrics:
    """The computed account picture (feeds ``AccountView``)."""

    equity: float
    portfolio_value: float
    buying_power: float
    used_buying_power: float
    available_margin: float
    open_risk: float
    daily_pnl: float
    total_pnl: float
    max_drawdown: float
    trade_count: int
    win_rate: float | None
    sharpe: float | None
    expectancy_r: float | None


def compute_account_metrics(
    *,
    settled_cash: float,
    unsettled_cash: float,
    positions_market_value: float,
    positions_cost_basis: float,
    open_risk: float,
    starting_cash: float,
    margin_multiplier: float,
    day_start_equity: float | None,
    equity_history: list[float],
    closed_r_multiples: list[float],
    closed_pnls: list[float],
) -> AccountMetrics:
    """All account metrics from raw facts (pure, total)."""
    cash = settled_cash + unsettled_cash
    equity = cash + positions_market_value
    trade_count = len(closed_pnls)
    wins = sum(1 for p in closed_pnls if p > 0)
    win_rate = safe_divide(wins, trade_count, default=0.0) if trade_count else None
    exp_r = float(expectancy(closed_r_multiples)) if closed_r_multiples else None
    history = [*equity_history, equity]
    buying_power = max(settled_cash, 0.0) * margin_multiplier
    return AccountMetrics(
        equity=equity,
        portfolio_value=positions_market_value,
        buying_power=buying_power,
        used_buying_power=positions_cost_basis,
        available_margin=max(equity * margin_multiplier - positions_cost_basis, 0.0),
        open_risk=open_risk,
        daily_pnl=equity - (day_start_equity if day_start_equity is not None else equity),
        total_pnl=equity - starting_cash,
        max_drawdown=max_drawdown(history),
        trade_count=trade_count,
        win_rate=win_rate,
        sharpe=sharpe_ratio(history),
        expectancy_r=exp_r,
    )
