"""The Home-Run instrument selector.

Given a *qualified Home-Run trade*, choose the optimal way to express it —
**Shares**, **ATM Calls**, **Slightly-ITM Calls**, a **Call Debit Spread** or
**LEAPS** — from six decision factors: expected move, time horizon, IV rank,
options liquidity, account size and risk budget.

``HomeRunInstrumentSelector.recommend(trade)`` scores all five expressions
(bounded ``[0, 1]`` factor sub-scores, weighted and re-normalized), applies hard
liquidity gates, picks the best-fit, and returns a
:class:`HomeRunRecommendation` with a suggested structure (moneyness, expiry,
sizing) and a plain-language explanation. It chooses *how* to express a home run;
it does not size portfolio risk or route orders.

Factor → instrument intuition (all bullish, differing in cost / leverage / decay /
capped-vs-open-ended payoff):

* **Shares** — the linear fallback: small expected move, very long/indefinite
  hold, rich IV (options expensive), ample account & risk budget, or when options
  are illiquid.
* **ATM Calls** — maximum convexity per dollar: large move, *cheap* IV (low rank),
  short horizon, small risk budget (leverage).
* **Slightly-ITM Calls** — higher delta, less extrinsic/theta than ATM: large
  move, *moderate* IV, medium horizon.
* **Call Debit Spread** — finance a long call by selling upside: *rich* IV (high
  rank), moderate move (capped), small account / tight budget.
* **LEAPS** — leveraged stock replacement for trend capture: long horizon, large
  move, cheap-ish IV.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from momentum.instruments.home_run_config import FactorWeights, HomeRunInstrumentConfig
from momentum.instruments.scoring import band, down, up


class HomeRunInstrument(str, Enum):
    """How a qualified home-run thesis is expressed in the market."""

    SHARES = "shares"
    ATM_CALL = "atm_call"
    ITM_CALL = "itm_call"  # slightly in-the-money
    CALL_DEBIT_SPREAD = "call_debit_spread"
    LEAPS = "leaps"

    @property
    def is_option(self) -> bool:
        return self is not HomeRunInstrument.SHARES

    @property
    def display(self) -> str:
        return {
            HomeRunInstrument.SHARES: "Shares",
            HomeRunInstrument.ATM_CALL: "ATM Calls",
            HomeRunInstrument.ITM_CALL: "Slightly-ITM Calls",
            HomeRunInstrument.CALL_DEBIT_SPREAD: "Call Debit Spread",
            HomeRunInstrument.LEAPS: "LEAPS",
        }[self]


@dataclass(frozen=True, slots=True)
class HomeRunTrade:
    """A qualified Home-Run trade plus the six instrument-decision factors."""

    symbol: str
    entry_price: float
    expected_move_pct: float  # home-run target upside (0.50 = +50%)
    horizon_days: int  # expected holding horizon
    iv_rank: float  # 0..1 (IV percentile vs the symbol's 1y range)
    options_liquidity: float = 1.0  # 0..1 (deep, tight chain = 1)
    leaps_available: bool = True  # liquid long-dated expiries listed
    account_size: float = 100_000.0
    risk_budget: float = 1_000.0  # $ at risk for this trade (1R)
    signal_id: int | None = None


@dataclass(frozen=True, slots=True)
class StructureSuggestion:
    """A concrete (approximate) structure for the chosen instrument."""

    instrument: HomeRunInstrument
    target_delta: float | None = None  # long-leg delta (None for shares)
    short_delta: float | None = None  # spread short-leg delta
    expiry_days: int | None = None
    shares: int | None = None
    contracts: int | None = None
    est_cost: float | None = None  # capital outlay ($) where computable
    max_risk: float | None = None  # defined risk ($)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.value,
            "target_delta": self.target_delta,
            "short_delta": self.short_delta,
            "expiry_days": self.expiry_days,
            "shares": self.shares,
            "contracts": self.contracts,
            "est_cost": _round(self.est_cost, 2),
            "max_risk": _round(self.max_risk, 2),
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class InstrumentCandidate:
    """One instrument's suitability score and the reasons behind it."""

    instrument: HomeRunInstrument
    score: float
    eligible: bool
    components: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.value,
            "score": round(self.score, 4),
            "eligible": self.eligible,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class HomeRunRecommendation:
    """The chosen instrument, a suggested structure and the explanation."""

    symbol: str
    instrument: HomeRunInstrument
    structure: StructureSuggestion
    confidence: float  # winning score
    margin: float  # gap to the runner-up (decisiveness)
    candidates: tuple[InstrumentCandidate, ...]
    explanation: tuple[str, ...]
    config_hash: str
    signal_id: int | None = None

    @property
    def runner_up(self) -> HomeRunInstrument | None:
        ranked = sorted(self.candidates, key=lambda c: c.score, reverse=True)
        return ranked[1].instrument if len(ranked) > 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument": self.instrument.value,
            "confidence": round(self.confidence, 4),
            "margin": round(self.margin, 4),
            "structure": self.structure.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "explanation": list(self.explanation),
            "config_hash": self.config_hash,
        }


# --------------------------------------------------------------------------- #
# Factor normalization + per-instrument scoring
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Factors:
    """The decision factors normalized into the sub-scores the scorers consume."""

    big_move: float
    small_move: float
    mod_move: float
    short_h: float
    med_h: float
    long_h: float
    iv_cheap: float
    iv_rich: float
    iv_mid: float
    tight_budget: float
    ample_budget: float
    big_account: float
    small_account: float
    liquidity: float


def _factors(trade: HomeRunTrade, cfg: HomeRunInstrumentConfig) -> _Factors:
    b = cfg.bands
    return _Factors(
        big_move=up(trade.expected_move_pct, b.move_small, b.move_large),
        small_move=down(trade.expected_move_pct, b.move_small, b.move_large),
        mod_move=band(
            trade.expected_move_pct,
            b.move_small * 0.5,
            b.move_small,
            b.move_large * 0.7,
            b.move_large,
        ),
        short_h=band(
            float(trade.horizon_days),
            5.0,
            float(b.short_horizon_days),
            float(b.medium_horizon_days),
            float(b.long_horizon_days),
        ),
        med_h=band(
            float(trade.horizon_days),
            float(b.short_horizon_days),
            float(b.medium_horizon_days),
            float(b.long_horizon_days),
            float(b.leaps_min_days),
        ),
        long_h=up(float(trade.horizon_days), float(b.medium_horizon_days), float(b.leaps_min_days)),
        iv_cheap=down(trade.iv_rank, b.iv_low, b.iv_high),
        iv_rich=up(trade.iv_rank, b.iv_low, b.iv_high),
        iv_mid=band(trade.iv_rank, 0.0, b.iv_low, b.iv_high, 1.0),
        tight_budget=down(trade.risk_budget, b.budget_small, b.budget_large),
        ample_budget=up(trade.risk_budget, b.budget_small, b.budget_large),
        big_account=up(trade.account_size, b.account_small, b.account_large),
        small_account=down(trade.account_size, b.account_small, b.account_large),
        liquidity=max(0.0, min(1.0, trade.options_liquidity)),
    )


def _blend(weights: FactorWeights, comps: dict[str, float]) -> float:
    """Weighted mean over the factors that carry weight (re-normalized)."""
    w = weights.as_dict()
    num = sum(w[name] * value for name, value in comps.items())
    den = sum(w[name] for name in comps)
    return num / den if den > 0 else 0.0


def _comps_shares(f: _Factors) -> dict[str, float]:
    return {
        "base": 1.0,
        "move": f.small_move,  # small move => linear shares fine
        "iv": f.iv_rich,  # rich options => own the stock
        "horizon": f.long_h,  # very long / indefinite hold
        "account": f.big_account,  # ample capital => use it
        "budget": f.ample_budget,  # ample risk budget => no need for leverage
    }


def _comps_atm_call(f: _Factors) -> dict[str, float]:
    return {
        "move": f.big_move,  # large move => convexity shines
        "iv": f.iv_cheap,  # cheap options => buy premium
        "horizon": f.short_h,  # short / medium horizon
        "budget": f.tight_budget,  # small budget => leverage
        "liquidity": f.liquidity,
    }


def _comps_itm_call(f: _Factors) -> dict[str, float]:
    return {
        "move": f.big_move,
        "iv": f.iv_mid,  # moderate IV: less extrinsic risk than ATM
        "horizon": f.med_h,  # medium horizon
        "budget": f.tight_budget,
        "account": 0.5,
        "liquidity": f.liquidity,
    }


def _comps_call_debit_spread(f: _Factors) -> dict[str, float]:
    return {
        "iv": f.iv_rich,  # rich options => sell upside to finance
        "move": f.mod_move,  # moderate move (capped upside acceptable)
        "horizon": f.short_h,
        "account": f.small_account,  # scarce capital => cheapest net debit
        "budget": f.tight_budget,
        "liquidity": f.liquidity,
    }


def _comps_leaps(f: _Factors) -> dict[str, float]:
    return {
        "horizon": f.long_h,  # long horizon => trend capture
        "move": f.big_move,
        "iv": f.iv_cheap,
        "account": f.big_account,  # enough capital for a pricier long-dated contract
        "budget": f.tight_budget,  # leverage vs shares
        "liquidity": f.liquidity,
    }


_COMPS: dict[HomeRunInstrument, Callable[[_Factors], dict[str, float]]] = {
    HomeRunInstrument.SHARES: _comps_shares,
    HomeRunInstrument.ATM_CALL: _comps_atm_call,
    HomeRunInstrument.ITM_CALL: _comps_itm_call,
    HomeRunInstrument.CALL_DEBIT_SPREAD: _comps_call_debit_spread,
    HomeRunInstrument.LEAPS: _comps_leaps,
}

# Weights config key per instrument.
_WEIGHT_KEY: dict[HomeRunInstrument, str] = {
    HomeRunInstrument.SHARES: "shares",
    HomeRunInstrument.ATM_CALL: "atm_call",
    HomeRunInstrument.ITM_CALL: "itm_call",
    HomeRunInstrument.CALL_DEBIT_SPREAD: "call_debit_spread",
    HomeRunInstrument.LEAPS: "leaps",
}

# Tie-break: prefer the simpler / less aggressive expression on equal scores.
_PRIORITY: dict[HomeRunInstrument, int] = {
    HomeRunInstrument.SHARES: 0,
    HomeRunInstrument.CALL_DEBIT_SPREAD: 1,
    HomeRunInstrument.ITM_CALL: 2,
    HomeRunInstrument.LEAPS: 3,
    HomeRunInstrument.ATM_CALL: 4,
}


class HomeRunInstrumentSelector:
    """Chooses shares / ATM / slightly-ITM calls / call spread / LEAPS for a home run."""

    def __init__(self, config: HomeRunInstrumentConfig | None = None) -> None:
        self.config = config or HomeRunInstrumentConfig()

    def recommend(self, trade: HomeRunTrade) -> HomeRunRecommendation:
        cfg = self.config
        f = _factors(trade, cfg)

        candidates: list[InstrumentCandidate] = []
        for instrument in HomeRunInstrument:
            comps = _COMPS[instrument](f)
            score = _blend(cfg.weights_for(_WEIGHT_KEY[instrument]), comps)
            is_eligible, reasons = self._eligibility(instrument, trade)
            candidates.append(InstrumentCandidate(instrument, score, is_eligible, comps, reasons))

        eligible = [c for c in candidates if c.eligible]
        pool = eligible or [c for c in candidates if c.instrument is HomeRunInstrument.SHARES]
        ranked = sorted(pool, key=lambda c: (-c.score, _PRIORITY[c.instrument]))
        winner = ranked[0]
        margin = winner.score - ranked[1].score if len(ranked) > 1 else winner.score

        structure = self._structure(winner.instrument, trade)
        explanation = self._explain(winner, ranked, trade, margin, structure)

        return HomeRunRecommendation(
            symbol=trade.symbol.upper(),
            instrument=winner.instrument,
            structure=structure,
            confidence=round(winner.score, 4),
            margin=round(margin, 4),
            candidates=tuple(candidates),
            explanation=explanation,
            config_hash=cfg.config_hash(),
            signal_id=trade.signal_id,
        )

    # -- gates -------------------------------------------------------------- #
    def _eligibility(
        self, instrument: HomeRunInstrument, trade: HomeRunTrade
    ) -> tuple[bool, tuple[str, ...]]:
        if instrument is HomeRunInstrument.SHARES:
            return True, ()  # the always-available fallback
        reasons: list[str] = []
        if trade.options_liquidity < self.config.min_options_liquidity:
            reasons.append("options liquidity below floor")
        if instrument is HomeRunInstrument.LEAPS and not trade.leaps_available:
            reasons.append("no liquid long-dated (LEAPS) expiries")
        return (not reasons, tuple(reasons))

    # -- structure ---------------------------------------------------------- #
    def _structure(self, instrument: HomeRunInstrument, trade: HomeRunTrade) -> StructureSuggestion:
        s = self.config.structure
        if instrument is HomeRunInstrument.SHARES:
            stop = self.config.bands.assumed_stop_pct
            shares = 0
            est_cost = None
            max_risk = None
            if trade.entry_price > 0 and stop > 0 and trade.risk_budget > 0:
                shares = int(trade.risk_budget / (trade.entry_price * stop))
                est_cost = shares * trade.entry_price
                max_risk = shares * trade.entry_price * stop
            return StructureSuggestion(
                instrument=instrument,
                shares=shares or None,
                est_cost=est_cost,
                max_risk=max_risk,
                notes=(
                    f"size from {stop:.0%} swing stop on a {trade.risk_budget:,.0f} risk budget",
                ),
            )

        dte = _clamp_int(trade.horizon_days, s.call_dte_min, s.call_dte_max)
        note = "buy contracts whose total debit ≈ the risk budget from live quotes"
        if instrument is HomeRunInstrument.ATM_CALL:
            return StructureSuggestion(
                instrument,
                target_delta=s.atm_delta,
                expiry_days=dte,
                max_risk=trade.risk_budget,
                notes=(note,),
            )
        if instrument is HomeRunInstrument.ITM_CALL:
            return StructureSuggestion(
                instrument,
                target_delta=s.itm_delta,
                expiry_days=dte,
                max_risk=trade.risk_budget,
                notes=(note,),
            )
        if instrument is HomeRunInstrument.CALL_DEBIT_SPREAD:
            return StructureSuggestion(
                instrument,
                target_delta=s.spread_long_delta,
                short_delta=s.spread_short_delta,
                expiry_days=dte,
                max_risk=trade.risk_budget,
                notes=(
                    "long ~{:.0%}Δ / short ~{:.0%}Δ; net debit ≈ the risk budget".format(
                        s.spread_long_delta, s.spread_short_delta
                    ),
                ),
            )
        # LEAPS
        leaps_dte = max(trade.horizon_days, self.config.bands.leaps_min_days)
        return StructureSuggestion(
            instrument,
            target_delta=s.leaps_delta,
            expiry_days=leaps_dte,
            max_risk=trade.risk_budget,
            notes=("deep-ITM long-dated call as a leveraged stock replacement",),
        )

    # -- explanation -------------------------------------------------------- #
    def _explain(
        self,
        winner: InstrumentCandidate,
        ranked: list[InstrumentCandidate],
        trade: HomeRunTrade,
        margin: float,
        structure: StructureSuggestion,
    ) -> tuple[str, ...]:
        out = [
            f"Recommend {winner.instrument.display} for {trade.symbol.upper()} "
            f"(home-run expression, score {winner.score:.2f})."
        ]
        drivers = sorted(winner.components.items(), key=lambda kv: kv[1], reverse=True)[:2]
        if drivers:
            out.append("Primary drivers: " + ", ".join(f"{n} {v:.2f}" for n, v in drivers) + ".")
        iv_word = (
            "cheap"
            if trade.iv_rank <= self.config.bands.iv_low
            else "rich"
            if trade.iv_rank >= self.config.bands.iv_high
            else "moderate"
        )
        out.append(
            f"Factors: expected move {trade.expected_move_pct:.0%}, horizon "
            f"{trade.horizon_days}d, IV rank {trade.iv_rank:.0%} ({iv_word}), "
            f"account ${trade.account_size:,.0f}, risk budget ${trade.risk_budget:,.0f}."
        )
        if structure.expiry_days is not None:
            delta = f"~{structure.target_delta:.0%}Δ " if structure.target_delta else ""
            out.append(f"Suggested structure: {delta}≈{structure.expiry_days}d expiry.")
        elif structure.shares:
            out.append(f"Suggested structure: {structure.shares} shares.")
        if len(ranked) > 1:
            out.append(f"Runner-up: {ranked[1].instrument.display} (margin {margin:.2f}).")
        if not winner.eligible:
            out.append("Note: shares fallback — no options expression was eligible.")
        elif any(not c.eligible for c in ranked):
            blocked = ", ".join(c.instrument.display for c in ranked if not c.eligible)
            out.append(f"Ineligible (gated): {blocked}.")
        return tuple(out)


def _clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _round(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)
