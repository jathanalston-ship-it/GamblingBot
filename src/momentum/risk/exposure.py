"""Exposure controls: gross/net caps and per-sector concentration limits.

A trade can be individually fine yet still be resized or vetoed because the
portfolio is already too concentrated. Prevents a sector bet masquerading as
diversification.
"""

from __future__ import annotations

import math

from momentum.core.constants import EPS

__all__ = ["gross_exposure", "net_exposure", "sector_weight", "shares_to_fit_sector"]


def gross_exposure(positions_notional: float, equity: float) -> float:
    """Total absolute exposure as a fraction of equity."""
    return positions_notional / equity if equity > EPS else 0.0


def net_exposure(signed_notional: float, equity: float) -> float:
    """Long-minus-short exposure as a fraction of equity."""
    return signed_notional / equity if equity > EPS else 0.0


def sector_weight(sector_notional: float, equity: float) -> float:
    """A sector's share of equity."""
    return sector_notional / equity if equity > EPS else 0.0


def shares_to_fit_sector(
    *,
    existing_sector_notional: float,
    equity: float,
    price: float,
    max_sector_weight: float,
) -> int:
    """Max whole shares addable to a sector without breaching its weight cap."""
    if price <= EPS:
        return 0
    room = max_sector_weight * equity - existing_sector_notional
    if room <= 0:
        return 0
    return int(math.floor(room / price))
