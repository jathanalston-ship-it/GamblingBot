"""Suggest a concrete structure for the chosen instrument.

Strikes, expiries and a rough cost/risk estimate. Option premiums use the
standard ATM approximation ``premium ≈ 0.4 · S · σ · √T`` (Brenner–Subrahmanyam),
adjusted for moneyness via intrinsic value — good enough for instrument choice
and sizing sanity, not for execution. Real quotes replace these later.
"""

from __future__ import annotations

import math

from momentum.core.enums import InstrumentType
from momentum.instruments.selection_config import InstrumentSelectionConfig
from momentum.instruments.types import InstrumentContext, InstrumentStructure, TradeThesis

_APPROX = "premium is an ATM approximation, not a live quote"


def _atm_premium(spot: float, iv: float, days: int) -> float:
    """Approximate ATM option premium (per share)."""
    t = max(days, 1) / 365.0
    return 0.4 * spot * max(iv, 1e-6) * math.sqrt(t)


def _call_premium(spot: float, strike: float, iv: float, days: int) -> float:
    """Rough call premium = intrinsic + time value (scaled ATM premium)."""
    intrinsic = max(0.0, spot - strike)
    atm = _atm_premium(spot, iv, days)
    # time value fades as the option goes deep ITM/OTM
    moneyness = abs(spot - strike) / max(spot, 1e-6)
    time_value = atm * max(0.0, 1.0 - moneyness)
    return intrinsic + time_value


def build_structure(
    instrument: InstrumentType,
    thesis: TradeThesis,
    ctx: InstrumentContext,
    cfg: InstrumentSelectionConfig,
) -> InstrumentStructure:
    spot = thesis.entry_price
    budget = ctx.risk_budget

    if instrument is InstrumentType.SHARES:
        shares = int(budget // spot) if spot > 0 else 0
        return InstrumentStructure(
            instrument=instrument,
            shares=max(shares, 0),
            est_cost=round(shares * spot, 2),
            notes=("linear exposure; sizing finalised by the risk engine",),
        )

    if instrument is InstrumentType.LONG_CALL:
        dte = _clamp(int(thesis.holding_period_days * 1.5), cfg.call_dte_min, cfg.call_dte_max)
        strike = round(spot, 2)  # ~ATM
        prem = _call_premium(spot, strike, ctx.implied_vol_annual, dte)
        per_contract = prem * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        return InstrumentStructure(
            instrument=instrument,
            expiry_days=dte,
            long_strike=strike,
            target_delta=cfg.call_target_delta,
            contracts=max(contracts, 0),
            est_cost=round(contracts * per_contract, 2),
            max_loss=round(contracts * per_contract, 2),  # premium paid
            notes=(_APPROX, "max loss = premium paid; theta decays before expiry")
            + _budget_note(contracts),
        )

    if instrument is InstrumentType.VERTICAL_CALL_SPREAD:
        dte = _clamp(int(thesis.holding_period_days * 1.5), cfg.call_dte_min, cfg.call_dte_max)
        long_k = round(spot, 2)
        short_k = round(spot * (1.0 + max(thesis.expected_move_pct, 0.02)), 2)
        long_prem = _call_premium(spot, long_k, ctx.implied_vol_annual, dte)
        short_prem = _call_premium(spot, short_k, ctx.implied_vol_annual, dte)
        debit = max(long_prem - short_prem, 1e-6)
        width = short_k - long_k
        per_contract = debit * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        return InstrumentStructure(
            instrument=instrument,
            expiry_days=dte,
            long_strike=long_k,
            short_strike=short_k,
            target_delta=cfg.spread_long_delta,
            contracts=max(contracts, 0),
            est_cost=round(contracts * per_contract, 2),
            max_loss=round(contracts * per_contract, 2),  # net debit
            max_profit=round(contracts * max(width - debit, 0.0) * 100, 2),
            notes=(_APPROX, "defined risk = net debit; profit capped at the short strike")
            + _budget_note(contracts),
        )

    # LEAPS — long-dated, in-the-money stock replacement
    dte = max(cfg.leaps_hold_days, int(thesis.holding_period_days * 1.2))
    strike = round(spot * 0.8, 2)  # ITM ~0.75-0.8 delta
    prem = _call_premium(spot, strike, ctx.implied_vol_annual, dte)
    per_contract = prem * 100
    contracts = int(budget // per_contract) if per_contract > 0 else 0
    return InstrumentStructure(
        instrument=InstrumentType.LEAPS,
        expiry_days=dte,
        long_strike=strike,
        target_delta=cfg.leaps_target_delta,
        contracts=max(contracts, 0),
        est_cost=round(contracts * per_contract, 2),
        max_loss=round(contracts * per_contract, 2),
        notes=(_APPROX, "ITM LEAPS as a stock replacement: leverage with low theta")
        + _budget_note(contracts),
    )


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _budget_note(contracts: int) -> tuple[str, ...]:
    if contracts <= 0:
        return ("risk budget below one-contract premium — size up budget or use shares",)
    return ()
