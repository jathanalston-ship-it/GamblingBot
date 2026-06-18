"""Position sizing: equity + stop distance + volatility -> share quantity.

Three interchangeable methods (selected in ``config/risk.yaml``). All return a
whole-share count and **never widen the stop**; the result is later clamped by
the per-name weight cap and the heat budget in the gateway.
"""

from __future__ import annotations

import math

from momentum.core.constants import EPS
from momentum.risk.risk_config import SizingConfig, SizingMethod

__all__ = [
    "fixed_fractional_shares",
    "vol_target_shares",
    "fractional_kelly_shares",
    "shares_for_weight",
    "size_position",
]


def fixed_fractional_shares(equity: float, risk_per_trade_pct: float, stop_distance: float) -> int:
    """Risk a fixed fraction of equity: ``floor(equity·risk% / stop_distance)``.

    Being stopped costs exactly ``risk_per_trade_pct`` of equity (≈ −1R),
    independent of the stock's price or volatility.
    """
    if stop_distance <= EPS:
        return 0
    risk_dollars = equity * risk_per_trade_pct
    return int(math.floor(risk_dollars / stop_distance))


def vol_target_shares(
    equity: float, target_vol_annual: float, sigma_annual: float, price: float
) -> int:
    """Size so the position contributes a target annualized volatility."""
    if sigma_annual <= EPS or price <= EPS:
        return 0
    notional = target_vol_annual * equity / sigma_annual
    return int(math.floor(notional / price))


def fractional_kelly_shares(
    equity: float,
    edge: float,
    odds: float,
    kelly_fraction: float,
    price: float,
    max_weight: float,
) -> int:
    """Capped fractional-Kelly sizing.

    ``f* = edge / odds`` is scaled by ``kelly_fraction`` (default ¼) and hard
    clamped to ``[0, max_weight]`` — full Kelly is too aggressive for real
    drawdowns.
    """
    if odds <= EPS or price <= EPS:
        return 0
    f_star = edge / odds
    weight = max(0.0, min(kelly_fraction * f_star, max_weight))
    return int(math.floor(weight * equity / price))


def shares_for_weight(equity: float, price: float, weight: float) -> int:
    """Whole shares for a target notional weight of equity."""
    if price <= EPS:
        return 0
    return int(math.floor(weight * equity / price))


def size_position(
    config: SizingConfig,
    *,
    equity: float,
    risk_per_trade_pct: float,
    stop_distance: float,
    price: float,
    sigma_annual: float | None = None,
    edge: float | None = None,
    odds: float | None = None,
) -> int:
    """Dispatch to the configured sizing method and return whole shares.

    ``risk_per_trade_pct`` is passed in already throttled (drawdown/regime), so
    the caller controls the effective risk budget.
    """
    if config.method is SizingMethod.FIXED_FRACTIONAL_RISK:
        return fixed_fractional_shares(equity, risk_per_trade_pct, stop_distance)
    if config.method is SizingMethod.VOL_TARGET:
        if sigma_annual is None or sigma_annual <= EPS:
            # fall back to fixed-fractional when no σ estimate is available
            return fixed_fractional_shares(equity, risk_per_trade_pct, stop_distance)
        return vol_target_shares(equity, config.vol_target_annual, sigma_annual, price)
    # fractional Kelly
    if edge is None or odds is None:
        return fixed_fractional_shares(equity, risk_per_trade_pct, stop_distance)
    return fractional_kelly_shares(
        equity, edge, odds, config.kelly_fraction, price, config.max_position_weight
    )
