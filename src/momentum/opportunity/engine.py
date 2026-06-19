"""The Home-Run-opportunity engine.

Blends six inputs into a 0-100 opportunity score, then classifies the setup into
one of three tiers — **Normal**, **Enhanced** or **Home Run** — capturing how
likely the trade is to produce an outsized, positive-skew winner.

The score is a transparent weighted blend (component contributions sum to the
score, exactly like the conviction engine). The *tier* is gated:

* **Home Run** — score >= ``home_run_min_score`` **and** every hard gate passes
  (a confirmed new all-time high, a favourable regime, strong relative volume and
  strong momentum, all at once). The conjunction of those rare conditions is what
  keeps Home Runs under the configured ``target_home_run_rate`` (< 5%); see
  ``momentum.opportunity.calibration`` to calibrate/verify the rate on real data.
* **Enhanced** — score >= ``enhanced_min_score`` (a strong setup, not the full stack).
* **Normal** — everything else.

Every decision is explainable: the per-component contributions and the pass/fail
of each Home-Run gate are returned and persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from momentum.opportunity.config import OpportunityConfig, OpportunityNormalization
from momentum.opportunity.inputs import OpportunityInputs


class OpportunityTier(str, Enum):
    """Discrete opportunity tier (ascending outsized-return potential)."""

    NORMAL = "normal"
    ENHANCED = "enhanced"
    HOME_RUN = "home_run"

    @property
    def is_home_run(self) -> bool:
        return self is OpportunityTier.HOME_RUN

    @property
    def display(self) -> str:
        return self.value.replace("_", " ").title()


@dataclass(frozen=True, slots=True)
class OpportunityComponent:
    """One input's contribution to the opportunity score."""

    name: str
    raw: float | None  # the raw input (mapped value for the regime label)
    normalized: float  # mapped to [0, 1]
    weight: float  # configured weight
    contribution: float  # points added to the final 0-100 score

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw": self.raw,
            "normalized": round(self.normalized, 4),
            "weight": self.weight,
            "contribution": round(self.contribution, 4),
        }


@dataclass(frozen=True, slots=True)
class GateCheck:
    """One Home-Run gate's outcome — pass/fail with the measured value and threshold."""

    name: str
    passed: bool
    detail: str
    value: float | None = None
    threshold: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "value": self.value,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class OpportunityResult:
    """The outcome of classifying one setup."""

    tier: OpportunityTier
    score: float
    new_ath: bool
    components: tuple[OpportunityComponent, ...]
    gates: tuple[GateCheck, ...]
    reasons: tuple[str, ...]
    config_hash: str
    model_version: str

    @property
    def is_home_run(self) -> bool:
        return self.tier.is_home_run

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(g.name for g in self.gates if not g.passed)

    def normalized_map(self) -> dict[str, float]:
        return {c.name: c.normalized for c in self.components}

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "score": self.score,
            "new_ath": self.new_ath,
            "config_hash": self.config_hash,
            "model_version": self.model_version,
            "reasons": list(self.reasons),
            "components": [c.to_dict() for c in self.components],
            "gates": [g.to_dict() for g in self.gates],
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _linear(value: float | None, lo: float, hi: float, neutral: float) -> float:
    """Linear map ``lo`` -> 0, ``hi`` -> 1 (clamped); missing -> neutral."""
    if value is None:
        return neutral
    if hi <= lo:
        return neutral
    return _clamp((value - lo) / (hi - lo))


def _inverted(value: float | None, max_: float, neutral: float) -> float:
    """Closeness map: 0 -> 1, ``max_`` (or beyond) -> 0; missing -> neutral."""
    if value is None:
        return neutral
    if max_ <= 0:
        return neutral
    return _clamp(1.0 - max(value, 0.0) / max_)


class HomeRunOpportunityEngine:
    """Turns :class:`OpportunityInputs` into a tiered :class:`OpportunityResult`."""

    def __init__(self, config: OpportunityConfig | None = None) -> None:
        self.config = config or OpportunityConfig()

    def classify(self, inputs: OpportunityInputs) -> OpportunityResult:
        n = self.config.normalization
        regime_norm = self._regime_value(inputs.market_regime, n)

        normalized: dict[str, float] = {
            "new_ath": self._new_ath(inputs, n),
            "momentum": _linear(inputs.momentum_score, n.momentum_lo, n.momentum_hi, n.neutral),
            "relative_volume": _linear(
                inputs.relative_volume, n.relative_volume_lo, n.relative_volume_hi, n.neutral
            ),
            "market_regime": regime_norm,
            "sector_leadership": _linear(
                inputs.sector_leadership, n.sector_leadership_lo, n.sector_leadership_hi, n.neutral
            ),
            "historical_analogs": self._historical(inputs, n),
        }
        raws: dict[str, float | None] = {
            "new_ath": 1.0 if inputs.new_ath else inputs.distance_to_ath,
            "momentum": inputs.momentum_score,
            "relative_volume": inputs.relative_volume,
            "market_regime": regime_norm,
            "sector_leadership": inputs.sector_leadership,
            "historical_analogs": inputs.historical_expectancy_r,
        }

        weights = self.config.weights.as_dict()
        total = sum(weights.values())
        components: list[OpportunityComponent] = []
        score = 0.0
        for name, norm in normalized.items():
            weight = weights[name]
            contribution = (norm * weight / total) * 100.0 if total > 0 else 0.0
            score += contribution
            components.append(OpportunityComponent(name, raws[name], norm, weight, contribution))
        score = round(score, 2)

        gates = self._home_run_gates(inputs, regime_norm)
        tier, reasons = self._classify(score, gates)

        return OpportunityResult(
            tier=tier,
            score=score,
            new_ath=inputs.new_ath,
            components=tuple(components),
            gates=tuple(gates),
            reasons=tuple(reasons),
            config_hash=self.config.config_hash(),
            model_version=self.config.model_version,
        )

    # -- tier decision ------------------------------------------------------ #
    def _classify(self, score: float, gates: list[GateCheck]) -> tuple[OpportunityTier, list[str]]:
        t = self.config.tiers
        gates_pass = all(g.passed for g in gates)
        if score >= t.home_run_min_score and gates_pass:
            return OpportunityTier.HOME_RUN, [
                f"Home Run: score {score:.1f} >= {t.home_run_min_score:.0f} and all "
                f"{len(gates)} gates passed."
            ]
        reasons: list[str] = []
        if score >= t.home_run_min_score and not gates_pass:
            failed = ", ".join(g.name for g in gates if not g.passed)
            reasons.append(f"Score {score:.1f} qualifies but Home-Run gates failed: {failed}.")
        if score >= t.enhanced_min_score:
            reasons.append(f"Enhanced: score {score:.1f} >= {t.enhanced_min_score:.0f}.")
            return OpportunityTier.ENHANCED, reasons
        reasons.append(f"Normal: score {score:.1f} < {t.enhanced_min_score:.0f}.")
        return OpportunityTier.NORMAL, reasons

    def _home_run_gates(self, inputs: OpportunityInputs, regime_norm: float) -> list[GateCheck]:
        t = self.config.tiers
        gates: list[GateCheck] = []

        if t.home_run_require_new_ath:
            ok = inputs.new_ath
            gates.append(
                GateCheck(
                    "new_ath",
                    ok,
                    "at a fresh all-time high" if ok else "not making a new all-time high",
                    value=1.0 if inputs.new_ath else 0.0,
                    threshold=1.0,
                )
            )

        regime_ok = regime_norm >= t.home_run_min_regime_score
        gates.append(
            GateCheck(
                "market_regime",
                regime_ok,
                f"regime score {regime_norm:.2f} "
                f"{'meets' if regime_ok else 'below'} {t.home_run_min_regime_score:.2f}",
                value=round(regime_norm, 4),
                threshold=t.home_run_min_regime_score,
            )
        )

        rvol = inputs.relative_volume
        rvol_ok = rvol is not None and rvol >= t.home_run_min_relative_volume
        gates.append(
            GateCheck(
                "relative_volume",
                rvol_ok,
                (
                    f"relative volume {rvol:.2f}x meets {t.home_run_min_relative_volume:.2f}x"
                    if rvol_ok and rvol is not None
                    else f"relative volume {'missing' if rvol is None else f'{rvol:.2f}x'} "
                    f"below {t.home_run_min_relative_volume:.2f}x"
                ),
                value=rvol,
                threshold=t.home_run_min_relative_volume,
            )
        )

        mom = inputs.momentum_score
        mom_ok = mom is not None and mom >= t.home_run_min_momentum
        gates.append(
            GateCheck(
                "momentum",
                mom_ok,
                (
                    f"momentum {mom:.2f} meets {t.home_run_min_momentum:.2f}"
                    if mom_ok and mom is not None
                    else f"momentum {'missing' if mom is None else f'{mom:.2f}'} "
                    f"below {t.home_run_min_momentum:.2f}"
                ),
                value=mom,
                threshold=t.home_run_min_momentum,
            )
        )
        return gates

    # -- normalization helpers --------------------------------------------- #
    @staticmethod
    def _regime_value(label: str | None, n: OpportunityNormalization) -> float:
        if label is None:
            return n.neutral
        return n.regime_map.get(label.lower(), n.neutral)

    @staticmethod
    def _new_ath(inputs: OpportunityInputs, n: OpportunityNormalization) -> float:
        """A fresh new high scores 1; otherwise partial credit by closeness."""
        if inputs.new_ath:
            return 1.0
        return _inverted(inputs.distance_to_ath, n.distance_to_ath_max, n.neutral)

    @staticmethod
    def _historical(inputs: OpportunityInputs, n: OpportunityNormalization) -> float:
        """Expectancy mapped to [0, 1], shrunk toward neutral for small samples."""
        if inputs.historical_expectancy_r is None or inputs.historical_sample_size <= 0:
            return n.neutral
        raw = _linear(
            inputs.historical_expectancy_r,
            n.historical_expectancy_lo,
            n.historical_expectancy_hi,
            n.neutral,
        )
        confidence = _clamp(inputs.historical_sample_size / n.historical_min_sample)
        return n.neutral + (raw - n.neutral) * confidence
