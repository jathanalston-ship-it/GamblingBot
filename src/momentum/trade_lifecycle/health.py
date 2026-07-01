"""Trade Health — the trade's battery percentage, fully explainable (pure).

Eight weighted components blend into a 0-100 score. Each component reports the
points it earned out of the points available, the delta versus a neutral
reading, and a plain-language detail quoting the measured values that produced
it — so every point gained or lost is accounted for. Never a black-box score.

Components (weights in ``config.health_weights``):

    conviction        current conviction level + change since entry
    trend             momentum + relative-strength direction
    volume            participation vs the trailing norm
    volatility        ATR expansion since entry (blowouts drain health)
    regime            market regime vs entry (worsening drains, bull sustains)
    sector            the sector's relative-strength percentile + change
    time_decay        thesis age vs the expected holding window
    analog_confidence historical analog expectancy, shrunk for small samples
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from momentum.trade_lifecycle.config import TradeLifecycleConfig
from momentum.trade_lifecycle.evaluation import (
    _clamp,
    _delta_component,
    _regime_worsened,
    _trend_component,
    conviction_delta,
    regime_changed,
)
from momentum.trade_lifecycle.types import EvaluationInputs, Trend

_NEUTRAL = 0.5


@dataclass(frozen=True, slots=True)
class HealthComponent:
    """One health input's contribution — points earned, and why."""

    name: str
    weight: float
    available: float  # points this component can contribute (weight-normalized)
    earned: float  # points actually contributed
    delta: float  # earned - neutral: points gained (+) or lost (-) vs no-evidence
    detail: str  # the measured values behind the points

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "available": round(self.available, 2),
            "earned": round(self.earned, 2),
            "delta": round(self.delta, 2),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class TradeHealthScore:
    """The 0-100 health score plus its full per-component accounting."""

    score: float
    components: tuple[HealthComponent, ...]

    def breakdown(self) -> tuple[dict[str, Any], ...]:
        return tuple(c.to_dict() for c in self.components)


def _conviction_fraction(inputs: EvaluationInputs, cfg: TradeLifecycleConfig) -> tuple[float, str]:
    if inputs.current_conviction is None:
        return _NEUTRAL, "no conviction reading — neutral"
    level = _clamp(inputs.current_conviction / 100.0)
    delta = conviction_delta(inputs.current_conviction, inputs.original_conviction)
    if delta is None:
        return level, f"conviction {inputs.current_conviction:.0f}/100 (no entry baseline)"
    delta_frac = _delta_component(
        delta, drop_full=cfg.conviction_drop_full, gain_full=cfg.conviction_gain_full
    )
    frac = (level + delta_frac) / 2.0
    return frac, f"conviction {inputs.current_conviction:.0f}/100, {delta:+.0f} since entry"


def _trend_fraction(momentum: Trend, rs: Trend) -> tuple[float, str]:
    frac = (_trend_component(momentum) + _trend_component(rs)) / 2.0
    return frac, f"momentum {momentum.value.lower()}, relative strength {rs.value.lower()}"


def _volume_fraction(volume: Trend, ratio: float | None) -> tuple[float, str]:
    if ratio is None:
        return _NEUTRAL, "no volume reading — neutral"
    return (
        _trend_component(volume),
        f"5d/20d volume ratio {ratio:.2f} ({volume.value.lower()})",
    )


def _volatility_fraction(expansion: float | None, cfg: TradeLifecycleConfig) -> tuple[float, str]:
    if expansion is None:
        return _NEUTRAL, "no ATR baseline — neutral"
    frac = _clamp(1.0 - max(expansion - 1.0, 0.0) / (cfg.atr_expansion_max - 1.0))
    if expansion <= 1.0:
        return frac, f"ATR {expansion:.2f}x entry — volatility contained"
    return frac, f"ATR expanded {expansion:.2f}x since entry"


def _regime_fraction(inputs: EvaluationInputs) -> tuple[float, str]:
    at_entry, now = inputs.regime_at_entry, inputs.regime_now
    if at_entry is None or now is None:
        return _NEUTRAL, "no regime reading — neutral"
    if _regime_worsened(at_entry, now):
        return 0.0, f"regime worsened: {at_entry} → {now}"
    if regime_changed(at_entry, now):
        return 1.0, f"regime improved: {at_entry} → {now}"
    frac = 1.0 if now.lower() in ("bull", "bullish") else 0.75
    return frac, f"regime unchanged ({now})"


def _sector_fraction(inputs: EvaluationInputs) -> tuple[float, str]:
    now = inputs.sector_rs_now
    if now is None:
        return _NEUTRAL, "no sector reading — neutral"
    delta = now - inputs.sector_rs_at_entry if inputs.sector_rs_at_entry is not None else None
    if delta is None:
        return _clamp(now), f"sector RS percentile {now:.2f}"
    return _clamp(now), f"sector RS percentile {now:.2f}, {delta:+.2f} since entry"


def _time_decay_fraction(days_held: float | None, cfg: TradeLifecycleConfig) -> tuple[float, str]:
    if days_held is None:
        return _NEUTRAL, "holding time unknown — neutral"
    if days_held <= cfg.time_decay_grace_days:
        return (
            1.0,
            f"held {days_held:.0f}d — inside the {cfg.time_decay_grace_days:.0f}d grace window",
        )
    span = cfg.time_decay_full_days - cfg.time_decay_grace_days
    frac = _clamp(1.0 - (days_held - cfg.time_decay_grace_days) / span)
    return frac, (
        f"held {days_held:.0f}d — thesis aging past {cfg.time_decay_grace_days:.0f}d "
        f"(fully decayed at {cfg.time_decay_full_days:.0f}d)"
    )


def _analog_fraction(inputs: EvaluationInputs, cfg: TradeLifecycleConfig) -> tuple[float, str]:
    expectancy = inputs.analog_expectancy_now
    if expectancy is None:
        return _NEUTRAL, "no comparable historical trades — neutral"
    level = _delta_component(
        expectancy, drop_full=cfg.analog_delta_full, gain_full=cfg.analog_delta_full
    )
    confidence = _clamp(inputs.analog_sample_size / cfg.analog_min_sample)
    frac = _NEUTRAL + (level - _NEUTRAL) * confidence
    return frac, (
        f"similar setups (same regime+sector) average {expectancy:+.2f}R "
        f"over {inputs.analog_sample_size} trades"
    )


def compute_health(
    inputs: EvaluationInputs,
    *,
    momentum_trend: Trend,
    rs_trend: Trend,
    volume_trend: Trend,
    expansion: float | None,
    config: TradeLifecycleConfig,
) -> TradeHealthScore:
    """Blend the eight components into the trade's battery percentage."""
    cfg = config
    fractions: dict[str, tuple[float, str]] = {
        "conviction": _conviction_fraction(inputs, cfg),
        "trend": _trend_fraction(momentum_trend, rs_trend),
        "volume": _volume_fraction(volume_trend, inputs.volume_ratio),
        "volatility": _volatility_fraction(expansion, cfg),
        "regime": _regime_fraction(inputs),
        "sector": _sector_fraction(inputs),
        "time_decay": _time_decay_fraction(inputs.days_held, cfg),
        "analog_confidence": _analog_fraction(inputs, cfg),
    }

    weights = cfg.health_weights.as_dict()
    total = sum(weights.values())
    components: list[HealthComponent] = []
    score = 0.0
    for name, (frac, detail) in fractions.items():
        weight = weights[name]
        available = (weight / total) * 100.0 if total > 0 else 0.0
        earned = frac * available
        score += earned
        components.append(
            HealthComponent(
                name=name,
                weight=weight,
                available=available,
                earned=earned,
                delta=earned - _NEUTRAL * available,
                detail=detail,
            )
        )
    return TradeHealthScore(score=round(_clamp(score, 0.0, 100.0), 2), components=tuple(components))
