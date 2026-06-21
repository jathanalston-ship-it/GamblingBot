"""Value objects for the options-recommendation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OptionStructure(str, Enum):
    """The three recommendable structures, in the fixed preference order.

    ``preference_rank`` (0 = most preferred) encodes the platform rule:
    1. Deep ITM Calls, 2. ATM Calls, 3. Vertical Call Spreads. It is the
    tie-break when two structures score equally.
    """

    DEEP_ITM_CALL = "deep_itm_call"
    ATM_CALL = "atm_call"
    VERTICAL_SPREAD = "vertical_spread"

    @property
    def preference_rank(self) -> int:
        return {
            OptionStructure.DEEP_ITM_CALL: 0,
            OptionStructure.ATM_CALL: 1,
            OptionStructure.VERTICAL_SPREAD: 2,
        }[self]

    @property
    def is_spread(self) -> bool:
        return self is OptionStructure.VERTICAL_SPREAD

    @property
    def display(self) -> str:
        return {
            OptionStructure.DEEP_ITM_CALL: "Deep ITM Call",
            OptionStructure.ATM_CALL: "ATM Call",
            OptionStructure.VERTICAL_SPREAD: "Vertical Call Spread",
        }[self]


class RiskLevel(str, Enum):
    """Qualitative risk band for a recommended structure."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


@dataclass(frozen=True, slots=True)
class RecommendationInputs:
    """Per-setup evidence for the options-recommendation decision.

    The setup is assumed to already have cleared the options-eligibility gate
    (``setup_eligible``); this engine chooses *which* contract to express it with.
    ``iv`` is the annualized implied vol as a fraction (0.45 = 45%); if absent it
    is derived from ``atr_pct``. ``iv_rank`` (0..1) drives structure selection.
    """

    symbol: str
    price: float
    atr_pct: float | None = None  # daily ATR / price
    expected_move_pct: float | None = None  # over the hold; else ATR-derived
    horizon_days: int | None = None
    iv: float | None = None  # annualized implied vol (fraction)
    iv_rank: float | None = None  # 0..1 percentile
    dollar_volume: float | None = None  # underlying ADV ($)
    option_spread_pct: float | None = None  # est. option bid/ask as fraction of mid
    risk_budget: float | None = None  # $ at risk (1R / target max loss)
    account_equity: float | None = None
    regime: str | None = None
    setup_eligible: bool = True


@dataclass(frozen=True, slots=True)
class AvoidGate:
    """One AVOID gate's outcome — pass/fail with a human-readable reason."""

    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class StructureCandidate:
    """One structure's suitability score and the factor sub-scores behind it."""

    structure: OptionStructure
    score: float
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure": self.structure.value,
            "display": self.structure.display,
            "score": round(self.score, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
        }


@dataclass(frozen=True, slots=True)
class ContractRecommendation:
    """A concrete (approximate) contract recommendation for one structure."""

    structure: OptionStructure
    expiration_days: int
    strike: float
    delta: float
    short_strike: float | None = None  # vertical-spread short leg
    short_delta: float | None = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    contracts: int = 0
    est_premium_per_contract: float = 0.0  # $ (×100 multiplier applied)
    max_loss: float = 0.0  # $ for the sized position
    target_profit: float = 0.0  # $ for the sized position
    suggested_allocation: float = 0.0  # $ premium outlay for the position
    allocation_pct: float = 0.0  # of account equity
    reward_to_risk: float | None = None  # per-contract, count-independent

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure": self.structure.value,
            "display": self.structure.display,
            "expiration_days": self.expiration_days,
            "strike": round(self.strike, 2),
            "delta": round(self.delta, 2),
            "short_strike": None if self.short_strike is None else round(self.short_strike, 2),
            "short_delta": None if self.short_delta is None else round(self.short_delta, 2),
            "risk_level": self.risk_level.value,
            "contracts": self.contracts,
            "est_premium_per_contract": round(self.est_premium_per_contract, 2),
            "max_loss": round(self.max_loss, 2),
            "target_profit": round(self.target_profit, 2),
            "suggested_allocation": round(self.suggested_allocation, 2),
            "allocation_pct": round(self.allocation_pct, 4),
            "reward_to_risk": (
                None if self.reward_to_risk is None else round(self.reward_to_risk, 2)
            ),
        }


@dataclass(frozen=True, slots=True)
class OptionsRecommendation:
    """The chosen contract, the ranked alternatives, gates and risk disclosures."""

    symbol: str
    recommended: bool
    structure: OptionStructure | None
    contract: ContractRecommendation | None
    expected_move_pct: float | None
    candidates: tuple[StructureCandidate, ...]
    gates: tuple[AvoidGate, ...]
    risk_disclosures: tuple[str, ...]
    summary: str
    config_hash: str

    @property
    def blocking_gates(self) -> tuple[str, ...]:
        return tuple(g.name for g in self.gates if not g.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "recommended": self.recommended,
            "structure": None if self.structure is None else self.structure.value,
            "contract": None if self.contract is None else self.contract.to_dict(),
            "expected_move_pct": (
                None if self.expected_move_pct is None else round(self.expected_move_pct, 4)
            ),
            "candidates": [c.to_dict() for c in self.candidates],
            "gates": [g.to_dict() for g in self.gates],
            "risk_disclosures": list(self.risk_disclosures),
            "summary": self.summary,
            "config_hash": self.config_hash,
        }
