"""The thesis-reevaluation engine: inputs -> pure grading -> one evaluation.

The engine is a thin orchestrator over the pure functions in
:mod:`momentum.trade_lifecycle.evaluation`; assembling the inputs (bars,
conviction, regime, analogs, prior evaluations) is the service layer's job.
"""

from __future__ import annotations

from momentum.trade_lifecycle.config import TradeLifecycleConfig
from momentum.trade_lifecycle.evaluation import (
    atr_expansion,
    conviction_delta,
    decide_action,
    health_of,
    regime_changed,
    thesis_stability,
    thesis_strength,
    trend_of,
)
from momentum.trade_lifecycle.explain import build_explanation
from momentum.trade_lifecycle.health import compute_health
from momentum.trade_lifecycle.types import EvaluationInputs, ThesisEvaluation


class ThesisReevaluationEngine:
    """Grades one open trade's thesis against fresh market evidence."""

    def __init__(self, config: TradeLifecycleConfig | None = None) -> None:
        self.config = config or TradeLifecycleConfig()

    def evaluate(self, inputs: EvaluationInputs) -> ThesisEvaluation:
        cfg = self.config
        momentum_trend = trend_of(
            inputs.momentum_now, inputs.momentum_prev, flat_band=cfg.trend_flat_band
        )
        rs_trend = trend_of(inputs.rs_now, inputs.rs_prev, flat_band=cfg.trend_flat_band)
        # volume_ratio is already "short avg / long avg": compare it to 1.0.
        volume_trend = trend_of(inputs.volume_ratio, 1.0, flat_band=cfg.trend_flat_band)
        expansion = atr_expansion(inputs.atr_now, inputs.atr_at_entry)

        strength = thesis_strength(
            inputs,
            momentum_trend=momentum_trend,
            rs_trend=rs_trend,
            volume_trend=volume_trend,
            expansion=expansion,
            config=cfg,
        )
        stability = thesis_stability((*inputs.prior_strengths, strength), config=cfg)
        action, reasons = decide_action(
            inputs,
            strength=strength,
            momentum_trend=momentum_trend,
            rs_trend=rs_trend,
            expansion=expansion,
            config=cfg,
        )
        health_score = compute_health(
            inputs,
            momentum_trend=momentum_trend,
            rs_trend=rs_trend,
            volume_trend=volume_trend,
            expansion=expansion,
            config=cfg,
        )
        explanation = build_explanation(
            inputs,
            health=health_score,
            action=action,
            reasons=reasons,
            momentum_trend=momentum_trend,
            rs_trend=rs_trend,
        )

        sector_delta = (
            inputs.sector_rs_now - inputs.sector_rs_at_entry
            if inputs.sector_rs_now is not None and inputs.sector_rs_at_entry is not None
            else None
        )
        analog_delta = (
            inputs.analog_expectancy_now - inputs.analog_expectancy_at_entry
            if inputs.analog_expectancy_now is not None
            and inputs.analog_expectancy_at_entry is not None
            else None
        )

        return ThesisEvaluation(
            symbol=inputs.symbol.upper(),
            current_conviction=inputs.current_conviction,
            conviction_delta=conviction_delta(
                inputs.current_conviction, inputs.original_conviction
            ),
            momentum_trend=momentum_trend,
            rs_trend=rs_trend,
            volume_trend=volume_trend,
            atr_expansion=expansion,
            regime_at_entry=inputs.regime_at_entry,
            regime_now=inputs.regime_now,
            regime_changed=regime_changed(inputs.regime_at_entry, inputs.regime_now),
            sector_delta=sector_delta,
            analog_delta=analog_delta,
            thesis_strength=strength,
            thesis_stability=stability,
            health=health_of(health_score.score, cfg),
            health_score=health_score.score,
            health_breakdown=health_score.breakdown(),
            action=action,
            reasons=reasons,
            price=inputs.price,
            stop_breached=inputs.price <= inputs.stop_price,
            explanation=explanation,
        )
