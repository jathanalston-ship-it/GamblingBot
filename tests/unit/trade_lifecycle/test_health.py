"""Tests for the explainable Trade Health score (the battery percentage)."""

from __future__ import annotations

import pytest

from momentum.trade_lifecycle import (
    EvaluationInputs,
    TradeLifecycleConfig,
    Trend,
    compute_health,
)

CFG = TradeLifecycleConfig()

EXPECTED_COMPONENTS = {
    "conviction",
    "trend",
    "volume",
    "volatility",
    "regime",
    "sector",
    "time_decay",
    "analog_confidence",
}


def _inputs(**overrides: object) -> EvaluationInputs:
    base: dict[str, object] = {
        "symbol": "TEST",
        "entry_price": 100.0,
        "stop_price": 92.0,
        "price": 105.0,
        "original_conviction": 70.0,
        "current_conviction": 72.0,
        "volume_ratio": 1.1,
        "atr_now": 2.2,
        "atr_at_entry": 2.0,
        "regime_at_entry": "bull",
        "regime_now": "bull",
        "sector_rs_at_entry": 0.7,
        "sector_rs_now": 0.75,
        "analog_expectancy_at_entry": 0.4,
        "analog_expectancy_now": 0.5,
        "analog_sample_size": 20,
        "days_held": 5.0,
    }
    base.update(overrides)
    return EvaluationInputs(**base)  # type: ignore[arg-type]


def _health(inputs: EvaluationInputs, **kw: object):  # type: ignore[no-untyped-def]
    return compute_health(
        inputs,
        momentum_trend=kw.get("momentum_trend", Trend.RISING),  # type: ignore[arg-type]
        rs_trend=kw.get("rs_trend", Trend.FLAT),  # type: ignore[arg-type]
        volume_trend=kw.get("volume_trend", Trend.FLAT),  # type: ignore[arg-type]
        expansion=kw.get("expansion", 1.1),  # type: ignore[arg-type]
        config=CFG,
    )


def test_all_eight_components_present() -> None:
    health = _health(_inputs())
    assert {c.name for c in health.components} == EXPECTED_COMPONENTS


def test_never_black_box_points_sum_to_score() -> None:
    """Every point of the score is accounted for by a named component."""
    health = _health(_inputs())
    assert health.score == pytest.approx(sum(c.earned for c in health.components), abs=0.02)
    assert sum(c.available for c in health.components) == pytest.approx(100.0, abs=0.01)


def test_every_component_explains_itself() -> None:
    health = _health(_inputs())
    for c in health.components:
        assert c.detail, f"{c.name} has no explanation"
        assert c.earned <= c.available + 1e-9
        assert c.earned >= 0


def test_explanations_quote_measured_values() -> None:
    health = _health(_inputs())
    by_name = {c.name: c.detail for c in health.components}
    assert "72" in by_name["conviction"] and "+2" in by_name["conviction"]
    assert "rising" in by_name["trend"]
    assert "1.10" in by_name["volume"]
    assert "1.10x" in by_name["volatility"]
    assert "bull" in by_name["regime"]
    assert "0.75" in by_name["sector"]
    assert "5d" in by_name["time_decay"]
    assert "+0.50R" in by_name["analog_confidence"] and "20 trades" in by_name["analog_confidence"]


def test_score_bounded_0_100() -> None:
    strong = _health(
        _inputs(current_conviction=100.0, sector_rs_now=1.0, analog_expectancy_now=2.0),
        momentum_trend=Trend.RISING,
        rs_trend=Trend.RISING,
        volume_trend=Trend.RISING,
        expansion=0.9,
    )
    weak = _health(
        _inputs(
            current_conviction=5.0,
            regime_now="bear",
            sector_rs_now=0.05,
            analog_expectancy_now=-2.0,
            days_held=90.0,
        ),
        momentum_trend=Trend.FALLING,
        rs_trend=Trend.FALLING,
        volume_trend=Trend.FALLING,
        expansion=3.5,
    )
    assert 0.0 <= weak.score < strong.score <= 100.0
    assert strong.score > 85.0
    assert weak.score < 20.0


def test_time_decay_drains_health() -> None:
    fresh = _health(_inputs(days_held=5.0))
    aging = _health(_inputs(days_held=40.0))
    ancient = _health(_inputs(days_held=90.0))
    assert fresh.score > aging.score > ancient.score
    decay = {c.name: c for c in ancient.components}["time_decay"]
    assert decay.earned == 0.0
    assert "90d" in decay.detail


def test_analog_confidence_shrinks_with_small_samples() -> None:
    big = _health(_inputs(analog_sample_size=50))
    tiny = _health(_inputs(analog_sample_size=1))
    big_analog = {c.name: c for c in big.components}["analog_confidence"]
    tiny_analog = {c.name: c for c in tiny.components}["analog_confidence"]
    # positive expectancy counts for less with 1 comparable trade
    assert tiny_analog.earned < big_analog.earned


def test_missing_inputs_are_neutral_not_zero() -> None:
    health = _health(
        EvaluationInputs(
            symbol="TEST",
            entry_price=100.0,
            stop_price=92.0,
            price=100.0,
            original_conviction=None,
            current_conviction=None,
        ),
        momentum_trend=Trend.FLAT,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.FLAT,
        expansion=None,
    )
    # days_held None + everything missing -> roughly neutral, never zero
    assert 40.0 <= health.score <= 60.0
    for c in health.components:
        if "neutral" in c.detail:
            assert c.delta == pytest.approx(0.0, abs=0.01)


def test_weights_are_configurable() -> None:
    cfg = TradeLifecycleConfig.from_dict({"health_weights": {"conviction": 10.0, "trend": 0.0}})
    health = compute_health(
        _inputs(),
        momentum_trend=Trend.RISING,
        rs_trend=Trend.RISING,
        volume_trend=Trend.FLAT,
        expansion=1.0,
        config=cfg,
    )
    by_name = {c.name: c for c in health.components}
    assert by_name["trend"].available == 0.0
    assert by_name["conviction"].available > 50.0


def test_deterministic() -> None:
    assert _health(_inputs()) == _health(_inputs())
