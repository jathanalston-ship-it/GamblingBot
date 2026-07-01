"""Tests for the thesis-reevaluation engine (wiring of the pure functions)."""

from __future__ import annotations

from momentum.trade_lifecycle import (
    EvaluationInputs,
    ThesisReevaluationEngine,
    TradeAction,
    TradeHealth,
    TradeLifecycleConfig,
    Trend,
)


def _inputs(**overrides: object) -> EvaluationInputs:
    base: dict[str, object] = {
        "symbol": "test",
        "entry_price": 100.0,
        "stop_price": 92.0,
        "price": 105.0,
        "original_conviction": 70.0,
        "current_conviction": 72.0,
        "momentum_now": 0.12,
        "momentum_prev": 0.10,
        "rs_now": 1.05,
        "rs_prev": 1.00,
        "volume_ratio": 1.02,
        "atr_now": 2.2,
        "atr_at_entry": 2.0,
        "regime_at_entry": "bull",
        "regime_now": "bull",
        "sector_rs_at_entry": 0.7,
        "sector_rs_now": 0.75,
        "analog_expectancy_at_entry": 0.4,
        "analog_expectancy_now": 0.5,
    }
    base.update(overrides)
    return EvaluationInputs(**base)  # type: ignore[arg-type]


def test_full_evaluation_populates_every_field() -> None:
    ev = ThesisReevaluationEngine().evaluate(_inputs())
    assert ev.symbol == "TEST"
    assert ev.current_conviction == 72.0
    assert ev.conviction_delta == 2.0
    assert ev.momentum_trend is Trend.RISING
    assert ev.rs_trend is Trend.FLAT  # +5% within the 10% flat band
    assert ev.atr_expansion == 1.1
    assert ev.regime_changed is False
    assert ev.sector_delta is not None and abs(ev.sector_delta - 0.05) < 1e-9
    assert ev.analog_delta is not None and abs(ev.analog_delta - 0.1) < 1e-9
    assert 0.0 <= ev.thesis_strength <= 100.0
    assert ev.thesis_stability == 1.0  # no prior history
    assert isinstance(ev.health, TradeHealth)
    assert isinstance(ev.action, TradeAction)
    assert ev.reasons
    assert ev.stop_breached is False


def test_stop_breach_marks_and_exits() -> None:
    ev = ThesisReevaluationEngine().evaluate(_inputs(price=90.0))
    assert ev.stop_breached is True
    assert ev.action is TradeAction.EXIT


def test_collapsed_thesis_exits_with_reasons() -> None:
    ev = ThesisReevaluationEngine().evaluate(
        _inputs(
            current_conviction=30.0,
            regime_now="bear",
            momentum_now=0.02,
            momentum_prev=0.10,
            rs_now=0.90,
            rs_prev=1.00,
            price=95.0,
        )
    )
    assert ev.action is TradeAction.EXIT
    assert ev.health in (TradeHealth.WEAKENING, TradeHealth.BROKEN)
    assert any("conviction" in r or "thesis" in r for r in ev.reasons)


def test_stability_uses_prior_strengths() -> None:
    engine = ThesisReevaluationEngine()
    steady = engine.evaluate(_inputs(prior_strengths=(70.0, 70.0, 70.0)))
    swinging = engine.evaluate(_inputs(prior_strengths=(20.0, 90.0, 20.0, 90.0)))
    assert steady.thesis_stability > swinging.thesis_stability


def test_to_record_round_trips_enums() -> None:
    record = ThesisReevaluationEngine().evaluate(_inputs()).to_record()
    assert record["momentum_trend"] in {t.value for t in Trend}
    assert record["health"] in {h.value for h in TradeHealth}
    assert record["action"] in {a.value for a in TradeAction}
    assert isinstance(record["reasons"], list)


def test_engine_respects_config() -> None:
    # With a huge flat band nothing trends; momentum Rising disappears.
    cfg = TradeLifecycleConfig.from_dict({"trend_flat_band": 10.0})
    ev = ThesisReevaluationEngine(cfg).evaluate(_inputs())
    assert ev.momentum_trend is Trend.FLAT


def test_deterministic() -> None:
    engine = ThesisReevaluationEngine()
    assert engine.evaluate(_inputs()) == engine.evaluate(_inputs())
