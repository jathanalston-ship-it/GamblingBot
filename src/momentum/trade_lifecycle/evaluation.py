"""Pure thesis-grading functions for open-trade reevaluation.

Everything here is a deterministic function of :class:`EvaluationInputs` and the
config — no I/O, no clock — which is what makes the engine trivially testable.
Missing inputs contribute a *neutral* reading (0.5) rather than zero, mirroring
the conviction engine: partial evidence neither inflates nor tanks the grade.
"""

from __future__ import annotations

from momentum.trade_lifecycle.config import TradeLifecycleConfig
from momentum.trade_lifecycle.types import (
    EvaluationInputs,
    Trend,
    TradeAction,
    TradeHealth,
)

_NEUTRAL = 0.5

# Regime ordering for "did the environment worsen?" (higher = more supportive).
_REGIME_RANK: dict[str, int] = {"bear": 0, "bearish": 0, "neutral": 1, "bull": 2, "bullish": 2}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def trend_of(now: float | None, prev: float | None, *, flat_band: float) -> Trend:
    """Direction of a metric between its prior and current reading.

    The change is measured relative to the prior magnitude; within ``±flat_band``
    it counts as Flat. Missing readings are Flat (no evidence of change).
    """
    if now is None or prev is None:
        return Trend.FLAT
    scale = max(abs(prev), 1e-12)
    change = (now - prev) / scale
    if change > flat_band:
        return Trend.RISING
    if change < -flat_band:
        return Trend.FALLING
    return Trend.FLAT


def atr_expansion(atr_now: float | None, atr_at_entry: float | None) -> float | None:
    """How much volatility has expanded since entry (1.0 = unchanged)."""
    if atr_now is None or atr_at_entry is None or atr_at_entry <= 0:
        return None
    return atr_now / atr_at_entry


def conviction_delta(current: float | None, original: float | None) -> float | None:
    if current is None or original is None:
        return None
    return current - original


def regime_changed(at_entry: str | None, now: str | None) -> bool:
    if at_entry is None or now is None:
        return False
    return _REGIME_RANK.get(at_entry.lower(), 1) != _REGIME_RANK.get(now.lower(), 1)


def _regime_worsened(at_entry: str | None, now: str | None) -> bool:
    if at_entry is None or now is None:
        return False
    return _REGIME_RANK.get(now.lower(), 1) < _REGIME_RANK.get(at_entry.lower(), 1)


def gain_r(price: float, entry: float, stop: float) -> float | None:
    """Unrealized gain in R (risk = entry - stop); None when risk is degenerate."""
    risk = entry - stop
    if risk <= 0:
        return None
    return (price - entry) / risk


def _trend_component(trend: Trend) -> float:
    if trend is Trend.RISING:
        return 1.0
    if trend is Trend.FALLING:
        return 0.0
    return _NEUTRAL


def _delta_component(delta: float | None, *, drop_full: float, gain_full: float) -> float:
    """Map a signed delta to [0, 1]: -drop_full -> 0, 0 -> neutral, +gain_full -> 1."""
    if delta is None:
        return _NEUTRAL
    if delta >= 0:
        return _NEUTRAL + _clamp(delta / gain_full) * (1.0 - _NEUTRAL)
    return _NEUTRAL * (1.0 - _clamp(-delta / drop_full))


def thesis_strength(
    inputs: EvaluationInputs,
    *,
    momentum_trend: Trend,
    rs_trend: Trend,
    volume_trend: Trend,
    expansion: float | None,
    config: TradeLifecycleConfig,
) -> float:
    """Blend the reevaluation evidence into a 0-100 thesis strength."""
    cfg = config
    delta = conviction_delta(inputs.current_conviction, inputs.original_conviction)

    regime_component = _NEUTRAL
    if inputs.regime_at_entry is not None and inputs.regime_now is not None:
        if _regime_worsened(inputs.regime_at_entry, inputs.regime_now):
            regime_component = 0.0
        elif regime_changed(inputs.regime_at_entry, inputs.regime_now):
            regime_component = 1.0  # changed but not worsened = improved
        else:
            regime_component = 1.0 if _REGIME_RANK.get(inputs.regime_now.lower(), 1) == 2 else 0.75

    volatility_component = _NEUTRAL
    if expansion is not None:
        # 1.0x (or calmer) -> 1; atr_expansion_max (or beyond) -> 0.
        volatility_component = _clamp(
            1.0 - max(expansion - 1.0, 0.0) / (cfg.atr_expansion_max - 1.0)
        )

    analog_component = _delta_component(
        None
        if inputs.analog_expectancy_now is None or inputs.analog_expectancy_at_entry is None
        else inputs.analog_expectancy_now - inputs.analog_expectancy_at_entry,
        drop_full=cfg.analog_delta_full,
        gain_full=cfg.analog_delta_full,
    )

    # Distance to stop as a fraction of the initial risk: at/below stop -> 0,
    # at entry -> 1 (capped — being far above entry is graded via gain, not here).
    risk = inputs.entry_price - inputs.stop_price
    price_component = _clamp((inputs.price - inputs.stop_price) / risk) if risk > 0 else _NEUTRAL

    components: dict[str, float] = {
        "conviction_level": (
            _clamp(inputs.current_conviction / 100.0)
            if inputs.current_conviction is not None
            else _NEUTRAL
        ),
        "conviction_delta": _delta_component(
            delta, drop_full=cfg.conviction_drop_full, gain_full=cfg.conviction_gain_full
        ),
        "momentum_trend": _trend_component(momentum_trend),
        "rs_trend": _trend_component(rs_trend),
        "volume_trend": _trend_component(volume_trend),
        "regime": regime_component,
        "volatility": volatility_component,
        "analog": analog_component,
        "price_vs_stop": price_component,
    }

    weights = cfg.weights.as_dict()
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    score = sum(components[name] * weights[name] for name in components) / total * 100.0
    return round(_clamp(score, 0.0, 100.0), 2)


def thesis_stability(prior_strengths: tuple[float, ...], *, config: TradeLifecycleConfig) -> float:
    """1 = strengths barely move between evaluations; 0 = wildly swinging.

    Uses the mean absolute successive change over the most recent
    ``stability_window`` strengths, scaled by ``stability_scale`` points.
    """
    window = prior_strengths[-config.stability_window :]
    if len(window) < 2:
        return 1.0
    diffs = [abs(b - a) for a, b in zip(window, window[1:], strict=False)]
    mean_diff = sum(diffs) / len(diffs)
    return round(1.0 - _clamp(mean_diff / config.stability_scale), 4)


def health_of(strength: float, config: TradeLifecycleConfig) -> TradeHealth:
    if strength >= config.strong_strength:
        return TradeHealth.STRONG
    if strength >= config.stable_strength:
        return TradeHealth.STABLE
    if strength >= config.weakening_strength:
        return TradeHealth.WEAKENING
    return TradeHealth.BROKEN


def decide_action(
    inputs: EvaluationInputs,
    *,
    strength: float,
    momentum_trend: Trend,
    rs_trend: Trend,
    expansion: float | None,
    config: TradeLifecycleConfig,
) -> tuple[TradeAction, tuple[str, ...]]:
    """The deterministic action cascade (most-defensive rule wins)."""
    cfg = config
    delta = conviction_delta(inputs.current_conviction, inputs.original_conviction)
    gain = gain_r(inputs.price, inputs.entry_price, inputs.stop_price)

    # 1. Stop breached — the plan's exit condition triggered.
    if inputs.price <= inputs.stop_price:
        return TradeAction.EXIT, (
            f"price {inputs.price:.2f} breached the stop {inputs.stop_price:.2f}",
        )

    # 2. Thesis broken.
    reasons: list[str] = []
    if strength < cfg.exit_strength:
        reasons.append(f"thesis strength {strength:.0f} below exit threshold")
    if delta is not None and delta <= -cfg.exit_conviction_drop:
        reasons.append(f"conviction collapsed ({delta:+.0f} points)")
    if (
        _regime_worsened(inputs.regime_at_entry, inputs.regime_now)
        and strength < cfg.stable_strength
    ):
        reasons.append(
            f"regime worsened ({inputs.regime_at_entry} -> {inputs.regime_now}) with a weak thesis"
        )
    if reasons:
        return TradeAction.EXIT, tuple(reasons)

    # 3. Thesis weakening — reduce.
    if strength < cfg.scale_out_strength:
        return TradeAction.SCALE_OUT, (f"thesis strength {strength:.0f} is weakening",)
    if momentum_trend is Trend.FALLING and rs_trend is Trend.FALLING:
        return TradeAction.SCALE_OUT, ("momentum and relative strength both falling",)

    # 4. Volatility expanded but the thesis holds — give the trade room.
    if (
        cfg.allow_lower_stop
        and expansion is not None
        and expansion >= cfg.lower_stop_atr_expansion
        and strength >= cfg.stable_strength
    ):
        return TradeAction.LOWER_STOP, (
            f"ATR expanded {expansion:.2f}x since entry with a stable thesis",
        )

    # 5. The trade has earned a tighter stop.
    if gain is not None and gain >= cfg.raise_stop_gain_r and strength >= cfg.stable_strength:
        return TradeAction.RAISE_STOP, (f"unrealized gain {gain:.1f}R — lock in progress",)

    # 6. Thesis strengthened — add.
    if (
        strength >= cfg.scale_in_strength
        and delta is not None
        and delta >= cfg.scale_in_conviction_gain
        and momentum_trend is Trend.RISING
    ):
        return TradeAction.SCALE_IN, (
            f"conviction up {delta:+.0f} with rising momentum and strength {strength:.0f}",
        )

    return TradeAction.HOLD, ("thesis intact — no change warranted",)
