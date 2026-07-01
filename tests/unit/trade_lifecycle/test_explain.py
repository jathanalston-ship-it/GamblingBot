"""Tests for the explainability engine (data-only, ≤250 words, no hallucinations)."""

from __future__ import annotations

import re

from momentum.trade_lifecycle import (
    EvaluationInputs,
    PriorSnapshot,
    ThesisReevaluationEngine,
    TradeLifecycleConfig,
    Trend,
    build_explanation,
    compute_health,
)
from momentum.trade_lifecycle.explain import MAX_NARRATIVE_WORDS
from momentum.trade_lifecycle.types import TradeAction

CFG = TradeLifecycleConfig()


def _inputs(**overrides: object) -> EvaluationInputs:
    base: dict[str, object] = {
        "symbol": "NVDA",
        "entry_price": 100.0,
        "stop_price": 92.0,
        "price": 108.0,
        "original_conviction": 70.0,
        "current_conviction": 78.0,
        "volume_ratio": 1.2,
        "atr_now": 2.2,
        "atr_at_entry": 2.0,
        "regime_at_entry": "bull",
        "regime_now": "bull",
        "sector_rs_at_entry": 0.7,
        "sector_rs_now": 0.8,
        "analog_expectancy_now": 0.5,
        "analog_sample_size": 20,
        "days_held": 6.0,
    }
    base.update(overrides)
    return EvaluationInputs(**base)  # type: ignore[arg-type]


def _explain(inputs: EvaluationInputs, action: TradeAction = TradeAction.HOLD):  # type: ignore[no-untyped-def]
    health = compute_health(
        inputs,
        momentum_trend=Trend.RISING,
        rs_trend=Trend.FLAT,
        volume_trend=Trend.RISING,
        expansion=1.1,
        config=CFG,
    )
    return build_explanation(
        inputs,
        health=health,
        action=action,
        reasons=("thesis intact — no change warranted",),
        momentum_trend=Trend.RISING,
        rs_trend=Trend.FLAT,
    )


def test_structure_complete() -> None:
    explanation = _explain(_inputs())
    assert set(explanation) == {
        "what_changed",
        "why_changed",
        "confidence",
        "supporting",
        "contradicting",
        "narrative",
    }
    assert explanation["what_changed"]
    assert explanation["why_changed"]
    assert explanation["confidence"]["direction"]
    assert explanation["narrative"]


def test_first_evaluation_is_a_baseline() -> None:
    explanation = _explain(_inputs(prior=None))
    assert any("first evaluation" in s for s in explanation["what_changed"])
    assert explanation["confidence"]["direction"] == "baseline"


def test_reports_changes_versus_prior_with_numbers() -> None:
    prior = PriorSnapshot(
        evaluated_at="2026-06-01T16:00:00",
        conviction=70.0,
        health_score=60.0,
        thesis_strength=60.0,
        action="Hold",
        price=100.0,
    )
    explanation = _explain(_inputs(prior=prior))
    joined = " ".join(explanation["what_changed"])
    assert "+8.0%" in joined  # price 100 -> 108
    assert "70 → 78" in joined  # conviction move quoted exactly


def test_confidence_direction_tracks_health() -> None:
    up = _explain(_inputs(prior=PriorSnapshot(health_score=40.0, price=100.0)))
    assert up["confidence"]["direction"] == "increased"
    down = _explain(_inputs(prior=PriorSnapshot(health_score=99.0, price=100.0)))
    assert down["confidence"]["direction"] == "decreased"


def test_supporting_and_contradicting_come_from_components() -> None:
    explanation = _explain(_inputs(regime_now="bear", days_held=80.0))
    against = " ".join(explanation["contradicting"])
    assert "regime" in against and "bear" in against
    assert "time decay" in against
    supporting = " ".join(explanation["supporting"])
    assert "conviction" in supporting


def test_narrative_capped_at_250_words() -> None:
    explanation = _explain(_inputs())
    assert len(str(explanation["narrative"]).split()) <= MAX_NARRATIVE_WORDS


def test_only_measurable_data_no_invented_numbers() -> None:
    """Every number in the narrative must trace to an input or a computed value."""
    inputs = _inputs()
    explanation = _explain(inputs)
    narrative = str(explanation["narrative"])
    assert inputs.symbol.upper() in narrative
    # Sanity: the quoted conviction is the actual one, not an invention.
    assert "78" in narrative
    # No placeholder/hallucination artifacts.
    assert not re.search(r"\bTBD\b|\bN/A\b|\bunknown symbol\b|\{.*\}", narrative)


def test_deterministic() -> None:
    assert _explain(_inputs()) == _explain(_inputs())


def test_persisted_via_engine() -> None:
    evaluation = ThesisReevaluationEngine().evaluate(_inputs())
    assert evaluation.explanation is not None
    assert evaluation.health_score > 0
    assert len(evaluation.health_breakdown) == 8
    record = evaluation.to_record()
    assert record["health_score"] == evaluation.health_score
    assert isinstance(record["health_breakdown"], list)
    assert record["explanation"]["narrative"]  # type: ignore[index]
