"""Options-eligibility scoring (pure logic).

Scores six factors — liquidity, volatility, expected move, time horizon, spread
quality, market regime — into a 0-100 confidence and a Shares-Preferred /
Leverage-Eligible verdict. A hard fail on liquidity, volatility or expected move
forces Shares Preferred regardless of the confidence. It recommends *whether* to
use options, never *which* contract.
"""

from __future__ import annotations

import math

from momentum.options_eligibility.config import OptionsEligibilityConfig, default_config
from momentum.options_eligibility.types import (
    EligibilityInputs,
    EligibilityResult,
    FactorAssessment,
    FactorStatus,
    Recommendation,
)

# Factors that, on a hard FAIL, veto options entirely.
_HARD_REQUIRED = frozenset({"liquidity", "volatility", "expected_move"})


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _ramp(value: float, lo: float, hi: float) -> float:
    """0 at ``lo`` → 1 at ``hi`` (clamped)."""
    if hi <= lo:
        return 1.0
    return _clamp((value - lo) / (hi - lo))


class OptionsEligibilityEngine:
    """Assess whether a setup is suitable for options leverage."""

    def __init__(self, config: OptionsEligibilityConfig | None = None) -> None:
        self.config = config or default_config()

    def assess(self, inputs: EligibilityInputs) -> EligibilityResult:
        cfg = self.config
        horizon = inputs.horizon_days or cfg.default_horizon_days
        expected_move = inputs.expected_move_pct
        if expected_move is None and inputs.atr_pct is not None:
            expected_move = inputs.atr_pct * math.sqrt(horizon)

        factors = [
            self._liquidity(inputs),
            self._volatility(inputs),
            self._expected_move(expected_move),
            self._time_horizon(horizon),
            self._spread_quality(inputs),
            self._market_regime(inputs),
        ]

        total_w = sum(f.weight for f in factors) or 1.0
        confidence = round(100.0 * sum(f.score * f.weight for f in factors) / total_w, 1)
        hard_fail = any(f.status is FactorStatus.FAIL and f.name in _HARD_REQUIRED for f in factors)
        eligible = (confidence >= cfg.eligible_confidence) and not hard_fail
        rec = Recommendation.LEVERAGE if eligible else Recommendation.SHARES

        return EligibilityResult(
            symbol=inputs.symbol,
            eligible=eligible,
            confidence=confidence,
            recommendation=rec,
            expected_move_pct=expected_move,
            factors=tuple(factors),
            summary=self._summary(eligible, confidence, factors, hard_fail),
        )

    # -- factors ------------------------------------------------------------- #
    def _liquidity(self, x: EligibilityInputs) -> FactorAssessment:
        cfg = self.config
        adv = x.dollar_volume
        if adv is None:
            return FactorAssessment(
                "liquidity",
                "Liquidity",
                FactorStatus.WARN,
                0.5,
                cfg.weights["liquidity"],
                "no volume data",
            )
        detail = f"${adv / 1e6:.0f}M ADV"
        if adv < cfg.liquidity_floor:
            return FactorAssessment(
                "liquidity",
                "Liquidity",
                FactorStatus.FAIL,
                _clamp(adv / cfg.liquidity_floor) * 0.3,
                cfg.weights["liquidity"],
                f"{detail} — below ${cfg.liquidity_floor / 1e6:.0f}M floor (options illiquid)",
            )
        score = 0.5 + 0.5 * _ramp(adv, cfg.liquidity_floor, cfg.liquidity_good)
        status = FactorStatus.PASS if adv >= cfg.liquidity_good else FactorStatus.WARN
        return FactorAssessment(
            "liquidity", "Liquidity", status, score, cfg.weights["liquidity"], detail
        )

    def _volatility(self, x: EligibilityInputs) -> FactorAssessment:
        cfg = self.config
        v = x.atr_pct
        if v is None:
            return FactorAssessment(
                "volatility",
                "Volatility",
                FactorStatus.WARN,
                0.5,
                cfg.weights["volatility"],
                "no ATR data",
            )
        detail = f"ATR {v * 100:.1f}%/day"
        if v < cfg.vol_min:
            return FactorAssessment(
                "volatility",
                "Volatility",
                FactorStatus.FAIL,
                _clamp(v / cfg.vol_min) * 0.4,
                cfg.weights["volatility"],
                f"{detail} — too quiet; premium not worth it",
            )
        if v <= cfg.vol_ideal_hi:
            score = 0.6 + 0.4 * _ramp(v, cfg.vol_min, cfg.vol_ideal_lo)
            status = FactorStatus.PASS if v >= cfg.vol_ideal_lo else FactorStatus.WARN
            return FactorAssessment(
                "volatility", "Volatility", status, _clamp(score), cfg.weights["volatility"], detail
            )
        # above the ideal band — pricey premium, but still tradeable
        score = 1.0 - 0.5 * _ramp(v, cfg.vol_ideal_hi, cfg.vol_max)
        return FactorAssessment(
            "volatility",
            "Volatility",
            FactorStatus.WARN,
            _clamp(score, 0.4, 1.0),
            cfg.weights["volatility"],
            f"{detail} — elevated (rich premium)",
        )

    def _expected_move(self, move: float | None) -> FactorAssessment:
        cfg = self.config
        if move is None:
            return FactorAssessment(
                "expected_move",
                "Expected Move",
                FactorStatus.WARN,
                0.5,
                cfg.weights["expected_move"],
                "unknown",
            )
        detail = f"{move * 100:.1f}% over hold"
        if move < cfg.move_min:
            return FactorAssessment(
                "expected_move",
                "Expected Move",
                FactorStatus.FAIL,
                _clamp(move / cfg.move_min) * 0.4,
                cfg.weights["expected_move"],
                f"{detail} — too small to clear premium",
            )
        score = 0.6 + 0.4 * _ramp(move, cfg.move_min, cfg.move_target)
        status = FactorStatus.PASS if move >= cfg.move_target else FactorStatus.WARN
        return FactorAssessment(
            "expected_move",
            "Expected Move",
            status,
            _clamp(score),
            cfg.weights["expected_move"],
            detail,
        )

    def _time_horizon(self, days: int) -> FactorAssessment:
        cfg = self.config
        detail = f"~{days}d hold"
        if days < cfg.horizon_min:
            return FactorAssessment(
                "time_horizon",
                "Time Horizon",
                FactorStatus.WARN,
                0.4,
                cfg.weights["time_horizon"],
                f"{detail} — very short (gamma risk)",
            )
        if days < cfg.horizon_ideal_lo:
            return FactorAssessment(
                "time_horizon",
                "Time Horizon",
                FactorStatus.WARN,
                0.6 + 0.4 * _ramp(days, cfg.horizon_min, cfg.horizon_ideal_lo),
                cfg.weights["time_horizon"],
                detail,
            )
        if days <= cfg.horizon_ideal_hi:
            return FactorAssessment(
                "time_horizon",
                "Time Horizon",
                FactorStatus.PASS,
                1.0,
                cfg.weights["time_horizon"],
                detail,
            )
        if days <= cfg.horizon_max:
            return FactorAssessment(
                "time_horizon",
                "Time Horizon",
                FactorStatus.WARN,
                1.0 - 0.5 * _ramp(days, cfg.horizon_ideal_hi, cfg.horizon_max),
                cfg.weights["time_horizon"],
                f"{detail} — long (theta favours shares/LEAPS)",
            )
        return FactorAssessment(
            "time_horizon",
            "Time Horizon",
            FactorStatus.WARN,
            0.3,
            cfg.weights["time_horizon"],
            f"{detail} — too long for short-dated options",
        )

    def _spread_quality(self, x: EligibilityInputs) -> FactorAssessment:
        cfg = self.config
        price, adv = x.price, x.dollar_volume
        if price is None or adv is None:
            return FactorAssessment(
                "spread_quality",
                "Spread Quality",
                FactorStatus.WARN,
                0.5,
                cfg.weights["spread_quality"],
                "estimated",
            )
        if price >= cfg.spread_min_price and adv >= cfg.spread_good_adv:
            return FactorAssessment(
                "spread_quality",
                "Spread Quality",
                FactorStatus.PASS,
                1.0,
                cfg.weights["spread_quality"],
                "liquid, higher-priced — tight spreads likely",
            )
        if price >= cfg.spread_min_price * 0.5 and adv >= cfg.spread_good_adv * 0.3:
            return FactorAssessment(
                "spread_quality",
                "Spread Quality",
                FactorStatus.WARN,
                0.6,
                cfg.weights["spread_quality"],
                "moderate — spreads may be wider",
            )
        return FactorAssessment(
            "spread_quality",
            "Spread Quality",
            FactorStatus.WARN,
            0.3,
            cfg.weights["spread_quality"],
            "low price / thin — wide option spreads likely",
        )

    def _market_regime(self, x: EligibilityInputs) -> FactorAssessment:
        cfg = self.config
        score = cfg.regime_score(x.regime)
        label = x.regime or "unknown"
        status = (
            FactorStatus.PASS
            if score >= 0.8
            else FactorStatus.WARN
            if score >= 0.5
            else FactorStatus.FAIL
        )
        return FactorAssessment(
            "market_regime",
            "Market Regime",
            status,
            score,
            cfg.weights["market_regime"],
            f"{label} regime",
        )

    @staticmethod
    def _summary(
        eligible: bool, confidence: float, factors: list[FactorAssessment], hard_fail: bool
    ) -> str:
        if eligible:
            strong = [f.label for f in factors if f.status is FactorStatus.PASS][:3]
            return (
                f"Leverage eligible ({confidence:.0f}/100) — " + ", ".join(strong) + " support it."
            )
        fails = [f.label for f in factors if f.status is FactorStatus.FAIL]
        if hard_fail and fails:
            return f"Shares preferred — {', '.join(fails).lower()} disqualifies options."
        return f"Shares preferred ({confidence:.0f}/100) — not enough edge for leverage."
