"""Tests for the pure thesis-grading functions."""

from __future__ import annotations

from momentum.trade_lifecycle import (
    EvaluationInputs,
    TradeAction,
    TradeHealth,
    TradeLifecycleConfig,
    Trend,
)
from momentum.trade_lifecycle.evaluation import (
    atr_expansion,
    conviction_delta,
    decide_action,
    gain_r,
    health_of,
    regime_changed,
    thesis_stability,
    thesis_strength,
    trend_of,
)

CFG = TradeLifecycleConfig()


def _inputs(**overrides: object) -> EvaluationInputs:
    base: dict[str, object] = {
        "symbol": "TEST",
        "entry_price": 100.0,
        "stop_price": 92.0,
        "price": 105.0,
        "original_conviction": 70.0,
        "current_conviction": 70.0,
    }
    base.update(overrides)
    return EvaluationInputs(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# trend_of
# --------------------------------------------------------------------------- #
def test_trend_directions() -> None:
    assert trend_of(1.2, 1.0, flat_band=0.1) is Trend.RISING
    assert trend_of(0.8, 1.0, flat_band=0.1) is Trend.FALLING
    assert trend_of(1.05, 1.0, flat_band=0.1) is Trend.FLAT


def test_trend_missing_is_flat() -> None:
    assert trend_of(None, 1.0, flat_band=0.1) is Trend.FLAT
    assert trend_of(1.0, None, flat_band=0.1) is Trend.FLAT


def test_trend_handles_negative_prior() -> None:
    # momentum can be negative; direction is still relative to magnitude
    assert trend_of(-0.05, -0.10, flat_band=0.1) is Trend.RISING


# --------------------------------------------------------------------------- #
# scalar helpers
# --------------------------------------------------------------------------- #
def test_atr_expansion() -> None:
    assert atr_expansion(3.0, 2.0) == 1.5
    assert atr_expansion(None, 2.0) is None
    assert atr_expansion(3.0, 0.0) is None


def test_conviction_delta() -> None:
    assert conviction_delta(55.0, 70.0) == -15.0
    assert conviction_delta(None, 70.0) is None


def test_regime_changed_ignores_synonyms() -> None:
    assert regime_changed("bull", "bullish") is False
    assert regime_changed("bull", "bear") is True
    assert regime_changed(None, "bull") is False


def test_gain_r() -> None:
    assert gain_r(108.0, 100.0, 92.0) == 1.0
    assert gain_r(100.0, 100.0, 100.0) is None  # degenerate risk


# --------------------------------------------------------------------------- #
# thesis strength
# --------------------------------------------------------------------------- #
def test_strength_neutral_when_everything_missing() -> None:
    inputs = _inputs(original_conviction=None, current_conviction=None, price=100.0)
    s = thesis_strength(
        inputs,
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=None,
        config=CFG,
    )
    # all components neutral except price_vs_stop (price at entry = 1.0)
    assert 50.0 <= s <= 70.0


def test_strength_monotonic_in_conviction() -> None:
    lo = thesis_strength(
        _inputs(current_conviction=40.0),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=None,
        config=CFG,
    )
    hi = thesis_strength(
        _inputs(current_conviction=90.0),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=None,
        config=CFG,
    )
    assert hi > lo


def test_strength_penalizes_regime_worsening() -> None:
    good = thesis_strength(
        _inputs(regime_at_entry="bull", regime_now="bull"),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=None,
        config=CFG,
    )
    bad = thesis_strength(
        _inputs(regime_at_entry="bull", regime_now="bear"),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=None,
        config=CFG,
    )
    assert bad < good


def test_strength_penalizes_volatility_blowout() -> None:
    calm = thesis_strength(
        _inputs(),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=1.0,
        config=CFG,
    )
    wild = thesis_strength(
        _inputs(),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=3.0,
        config=CFG,
    )
    assert wild < calm


def test_strength_bounded() -> None:
    s = thesis_strength(
        _inputs(current_conviction=100.0, price=200.0),
        momentum_trend=Trend.RISING,
        rs_trend=Trend.RISING,
        volume_trend=Trend.RISING,
        expansion=0.8,
        config=CFG,
    )
    assert 0.0 <= s <= 100.0


# --------------------------------------------------------------------------- #
# stability + health
# --------------------------------------------------------------------------- #
def test_stability_perfect_when_static() -> None:
    assert thesis_stability((60.0, 60.0, 60.0), config=CFG) == 1.0


def test_stability_low_when_swinging() -> None:
    assert thesis_stability((20.0, 80.0, 20.0, 80.0), config=CFG) < 0.2


def test_stability_defaults_to_one_with_short_history() -> None:
    assert thesis_stability((60.0,), config=CFG) == 1.0
    assert thesis_stability((), config=CFG) == 1.0


def test_health_bands() -> None:
    assert health_of(80.0, CFG) is TradeHealth.STRONG
    assert health_of(60.0, CFG) is TradeHealth.STABLE
    assert health_of(40.0, CFG) is TradeHealth.WEAKENING
    assert health_of(20.0, CFG) is TradeHealth.BROKEN


# --------------------------------------------------------------------------- #
# action cascade
# --------------------------------------------------------------------------- #
def _action(strength: float, inputs: EvaluationInputs, **kw: object) -> TradeAction:
    action, _ = decide_action(
        inputs,
        strength=strength,
        momentum_trend=kw.get("momentum_trend", Trend.FLAT),  # type: ignore[arg-type]
        rs_trend=kw.get("rs_trend", Trend.FLAT),  # type: ignore[arg-type]
        expansion=kw.get("expansion"),  # type: ignore[arg-type]
        config=CFG,
    )
    return action


def test_stop_breach_always_exits() -> None:
    inputs = _inputs(price=91.0)  # below the 92 stop
    assert _action(95.0, inputs) is TradeAction.EXIT


def test_broken_thesis_exits() -> None:
    assert _action(30.0, _inputs()) is TradeAction.EXIT


def test_conviction_collapse_exits() -> None:
    inputs = _inputs(current_conviction=40.0)  # -30 vs original 70
    assert _action(70.0, inputs) is TradeAction.EXIT


def test_regime_worsening_with_weak_thesis_exits() -> None:
    inputs = _inputs(regime_at_entry="bull", regime_now="bear")
    assert _action(50.0, inputs) is TradeAction.EXIT


def test_weakening_thesis_scales_out() -> None:
    assert _action(45.0, _inputs()) is TradeAction.SCALE_OUT


def test_momentum_and_rs_falling_scales_out() -> None:
    assert (
        _action(70.0, _inputs(), momentum_trend=Trend.FALLING, rs_trend=Trend.FALLING)
        is TradeAction.SCALE_OUT
    )


def test_volatility_expansion_lowers_stop_when_stable() -> None:
    assert _action(70.0, _inputs(), expansion=2.0) is TradeAction.LOWER_STOP


def test_earned_gain_raises_stop() -> None:
    inputs = _inputs(price=110.0)  # gain = (110-100)/(100-92) = 1.25R
    assert _action(70.0, inputs) is TradeAction.RAISE_STOP


def test_strengthened_thesis_scales_in() -> None:
    inputs = _inputs(price=104.0, current_conviction=80.0)  # +10, gain 0.5R
    assert _action(85.0, inputs, momentum_trend=Trend.RISING) is TradeAction.SCALE_IN


def test_default_is_hold() -> None:
    assert _action(70.0, _inputs(price=104.0)) is TradeAction.HOLD


def test_exit_wins_over_scale_in_conditions() -> None:
    # stop breached AND conviction up: the defensive rule wins
    inputs = _inputs(price=90.0, current_conviction=90.0)
    assert _action(90.0, inputs, momentum_trend=Trend.RISING) is TradeAction.EXIT
