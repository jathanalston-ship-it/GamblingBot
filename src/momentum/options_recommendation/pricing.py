"""Approximate, no-chain option-pricing helpers (pure functions).

These are deliberately simple closed-form approximations used *only* to size and
compare structures when no live option chain is available. They are not a pricing
model and carry no greeks beyond an assumed target delta — every recommendation
that uses them ships a risk disclosure to that effect.

The anchor is the Brenner-Subrahmanyam at-the-money approximation::

    C_atm ~= coeff * S * sigma * sqrt(T)        (coeff ~= 0.4, forward ~= spot)

The remaining extrinsic value of an in-/out-of-the-money call is scaled from the
ATM extrinsic by ``4 * d * (1 - d)`` (a unit-height parabola peaking at the money,
``d`` = |delta|), and intrinsic is added for calls that are in the money.
"""

from __future__ import annotations

import math

_TRADING_DAYS = 252.0
_CALENDAR_DAYS = 365.0
_CONTRACT_MULTIPLIER = 100.0


def annual_vol(iv: float | None, atr_pct: float | None, fallback: float) -> float:
    """Annualized vol from IV, else from daily ATR%, else the fallback."""
    if iv is not None and iv > 0:
        return iv
    if atr_pct is not None and atr_pct > 0:
        return atr_pct * math.sqrt(_TRADING_DAYS)
    return fallback


def atm_premium(spot: float, vol: float, dte: int, coeff: float) -> float:
    """Per-share ATM call premium (Brenner-Subrahmanyam)."""
    t_years = max(dte, 0) / _CALENDAR_DAYS
    return coeff * spot * vol * math.sqrt(t_years)


def _extrinsic_factor(delta: float) -> float:
    """Fraction of ATM extrinsic a call with |delta| ``d`` retains (0..1)."""
    d = min(max(delta, 0.0), 1.0)
    return max(0.0, min(1.0, 4.0 * d * (1.0 - d)))


def call_premium(spot: float, strike: float, delta: float, atm_ext: float) -> float:
    """Per-share premium = intrinsic + scaled ATM extrinsic (never negative)."""
    intrinsic = max(0.0, spot - strike)
    return max(0.0, intrinsic + atm_ext * _extrinsic_factor(delta))


def per_contract(value_per_share: float) -> float:
    """Scale a per-share value to one contract (×100)."""
    return value_per_share * _CONTRACT_MULTIPLIER


def call_value_at(target_price: float, strike: float) -> float:
    """Conservative (intrinsic-only) per-share call value at a target price."""
    return max(0.0, target_price - strike)
