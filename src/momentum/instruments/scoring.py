"""Per-instrument suitability scoring.

Each instrument's fit is a weighted blend of bounded ``[0, 1]`` sub-scores
derived from the thesis and the market context. Pure functions — the engine
applies the hard liquidity gates and picks the argmax.

The sub-scores encode the standard trade-offs:

* **Shares** — favoured by expensive options (high IV/RV), very long holds,
  small expected moves and ample capital room. The safe linear default.
* **Long calls** — favoured by large expected moves, short/medium holds, *cheap*
  options and a small risk budget (leverage).
* **Vertical call spreads** — favoured by *rich* options (sell premium),
  moderate moves, medium holds and scarce capital room.
* **LEAPS** — favoured by long holds (trend capture), large moves and cheap-ish
  options; the leveraged stock replacement.
"""

from __future__ import annotations

from momentum.instruments.selection_config import InstrumentSelectionConfig, InstrumentWeights
from momentum.instruments.types import InstrumentContext, TradeThesis


def up(x: float, lo: float, hi: float) -> float:
    """Ascending ramp: 0 at/below ``lo``, 1 at/above ``hi``."""
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def down(x: float, lo: float, hi: float) -> float:
    """Descending ramp: 1 at/below ``lo``, 0 at/above ``hi``."""
    return 1.0 - up(x, lo, hi)


def band(x: float, lo: float, peak_lo: float, peak_hi: float, hi: float) -> float:
    """Trapezoid: rises ``lo``→``peak_lo``, flat to ``peak_hi``, falls to ``hi``."""
    if x < peak_lo:
        return up(x, lo, peak_lo)
    if x <= peak_hi:
        return 1.0
    return down(x, peak_hi, hi)


def _blend(weights: InstrumentWeights, components: dict[str, float]) -> float:
    """Weighted mean of present components (re-normalized over used weights)."""
    w = weights.as_dict()
    num = 0.0
    den = 0.0
    for name, value in components.items():
        weight = w.get(name, 0.0)
        num += weight * value
        den += weight
    return num / den if den > 0 else 0.0


def _leverage_score(ctx: InstrumentContext, cfg: InstrumentSelectionConfig) -> float:
    """Small risk budgets favour leverage (options give more move per dollar)."""
    return down(ctx.risk_budget, cfg.small_risk_budget, cfg.large_risk_budget)


def score_shares(
    thesis: TradeThesis, ctx: InstrumentContext, cfg: InstrumentSelectionConfig
) -> tuple[float, dict[str, float]]:
    comps = {
        "base": 1.0,
        "iv_richness": up(ctx.iv_rv_ratio, cfg.iv_cheap, cfg.iv_rich),  # rich => shares
        "holding": up(thesis.holding_period_days, cfg.medium_hold_days, cfg.leaps_hold_days),
        "move": down(thesis.expected_move_pct, cfg.move_small, cfg.move_large),  # small move
        "exposure": up(ctx.available_exposure_pct, 0.2, 0.8),  # room => use capital
    }
    return _blend(cfg.shares, comps), comps


def score_long_call(
    thesis: TradeThesis, ctx: InstrumentContext, cfg: InstrumentSelectionConfig
) -> tuple[float, dict[str, float]]:
    comps = {
        "move": up(thesis.expected_move_pct, cfg.move_small, cfg.move_large),
        "holding": band(
            thesis.holding_period_days,
            3,
            cfg.short_hold_days,
            cfg.medium_hold_days,
            cfg.long_hold_days,
        ),
        "iv_richness": down(ctx.iv_rv_ratio, cfg.iv_cheap, cfg.iv_rich),  # cheap => buy
        "iv_level": down(ctx.implied_vol_annual, cfg.iv_level_low, cfg.iv_level_high),
        "leverage": _leverage_score(ctx, cfg),
    }
    return _blend(cfg.long_call, comps), comps


def score_vertical_call_spread(
    thesis: TradeThesis, ctx: InstrumentContext, cfg: InstrumentSelectionConfig
) -> tuple[float, dict[str, float]]:
    comps = {
        "iv_richness": up(ctx.iv_rv_ratio, cfg.iv_cheap, cfg.iv_rich),  # rich => sell premium
        "move": band(
            thesis.expected_move_pct,
            0.02,
            cfg.move_small,
            cfg.move_large * 0.7,
            cfg.move_large,
        ),  # moderate move (capped upside ok)
        "holding": band(
            thesis.holding_period_days,
            3,
            cfg.short_hold_days,
            cfg.medium_hold_days,
            cfg.long_hold_days,
        ),
        "leverage": _leverage_score(ctx, cfg),
        "exposure": down(ctx.available_exposure_pct, 0.2, 0.8),  # scarce room => efficient
    }
    return _blend(cfg.vertical_call_spread, comps), comps


def score_leaps(
    thesis: TradeThesis, ctx: InstrumentContext, cfg: InstrumentSelectionConfig
) -> tuple[float, dict[str, float]]:
    comps = {
        "holding": up(thesis.holding_period_days, cfg.medium_hold_days, cfg.leaps_hold_days),
        "move": up(thesis.expected_move_pct, cfg.move_small, cfg.move_large),
        "iv_richness": down(ctx.iv_rv_ratio, cfg.iv_cheap, cfg.iv_rich),
        "iv_level": down(ctx.implied_vol_annual, cfg.iv_level_low, cfg.iv_level_high),
        "leverage": _leverage_score(ctx, cfg),
    }
    return _blend(cfg.leaps, comps), comps
