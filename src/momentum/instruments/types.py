"""Immutable I/O value objects for the instrument-selection engine.

A :class:`TradeThesis` (what the strategy believes) plus an
:class:`InstrumentContext` (the market & portfolio conditions) go in; an
:class:`InstrumentDecision` — the chosen instrument, a suggested structure, and
the per-candidate scores that justify it — comes out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from momentum.core.enums import InstrumentType


@dataclass(frozen=True, slots=True)
class TradeThesis:
    """A bullish thesis emitted by the strategy."""

    symbol: str
    entry_price: float
    expected_move_pct: float  # target upside as a fraction (0.20 = +20%)
    holding_period_days: int  # expected horizon
    conviction: float = 0.5  # 0..1 (e.g. momentum score percentile)
    signal_id: int | None = None


@dataclass(frozen=True, slots=True)
class InstrumentContext:
    """Market & portfolio conditions that shape the instrument choice."""

    realized_vol_annual: float  # historical vol of the underlying
    implied_vol_annual: float  # ATM implied vol (option richness)
    risk_budget: float  # dollars at risk for this trade (1R from the risk engine)
    # --- liquidity ---------------------------------------------------------
    share_dollar_volume: float = 0.0  # underlying avg daily $ volume
    has_options: bool = True
    options_open_interest: float = 0.0  # ATM/near open interest
    options_spread_pct: float = 0.05  # bid-ask as a fraction of mid
    leaps_available: bool = True  # long-dated expiries listed & liquid
    # --- portfolio ---------------------------------------------------------
    available_exposure_pct: float = 1.0  # 0..1 capital room left (1 = lots of room)

    @property
    def iv_rv_ratio(self) -> float:
        """Implied / realized vol — options "richness" (>1 expensive)."""
        if self.realized_vol_annual <= 0:
            return 1.0
        return self.implied_vol_annual / self.realized_vol_annual


@dataclass(frozen=True, slots=True)
class InstrumentStructure:
    """A concrete (approximate) structure for the chosen instrument."""

    instrument: InstrumentType
    expiry_days: int | None = None  # None for shares
    long_strike: float | None = None
    short_strike: float | None = None  # only for spreads
    target_delta: float | None = None
    contracts: int | None = None  # option contracts (100 shares each)
    shares: int | None = None  # for the shares instrument
    est_cost: float | None = None  # net debit / capital outlay ($)
    max_loss: float | None = None  # defined risk ($) where applicable
    max_profit: float | None = None  # capped profit for spreads ($)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.value,
            "expiry_days": self.expiry_days,
            "long_strike": _round(self.long_strike),
            "short_strike": _round(self.short_strike),
            "target_delta": self.target_delta,
            "contracts": self.contracts,
            "shares": self.shares,
            "est_cost": _round(self.est_cost, 2),
            "max_loss": _round(self.max_loss, 2),
            "max_profit": _round(self.max_profit, 2),
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """One instrument's suitability score and the reasons behind it."""

    instrument: InstrumentType
    score: float  # 0..1
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
class InstrumentDecision:
    """The chosen instrument plus structure and full candidate scoring."""

    symbol: str
    instrument: InstrumentType
    structure: InstrumentStructure
    confidence: float  # top score
    margin: float  # gap to the runner-up (decisiveness)
    candidates: tuple[CandidateScore, ...]
    rationale: tuple[str, ...]
    iv_rv_ratio: float
    signal_id: int | None = None

    @property
    def runner_up(self) -> InstrumentType | None:
        ranked = sorted(self.candidates, key=lambda c: c.score, reverse=True)
        return ranked[1].instrument if len(ranked) > 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument": self.instrument.value,
            "confidence": round(self.confidence, 4),
            "margin": round(self.margin, 4),
            "iv_rv_ratio": round(self.iv_rv_ratio, 4),
            "structure": self.structure.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "rationale": list(self.rationale),
        }

    def to_record(self, *, run_id: str | None = None) -> dict[str, Any]:
        """Kwargs for the ``instrument_selections`` table."""
        s = self.structure
        return {
            "run_id": run_id,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "instrument": self.instrument.value,
            "confidence": round(self.confidence, 6),
            "margin": round(self.margin, 6),
            "iv_rv_ratio": round(self.iv_rv_ratio, 6),
            "expiry_days": s.expiry_days,
            "long_strike": s.long_strike,
            "short_strike": s.short_strike,
            "target_delta": s.target_delta,
            "contracts": s.contracts,
            "shares": s.shares,
            "est_cost": s.est_cost,
            "max_loss": s.max_loss,
            "max_profit": s.max_profit,
            "rationale": {"rationale": list(self.rationale)},
            "candidates": [c.to_dict() for c in self.candidates],
        }


def _round(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)
