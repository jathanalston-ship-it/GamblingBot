"""Tests for hindsight advice grading (pure outcome functions)."""

from __future__ import annotations

from momentum.trade_lifecycle import (
    AdviceGrade,
    AdviceVerdict,
    TradeAction,
    advice_summary,
    grade_advice,
    overall_accuracy,
)
from momentum.trade_lifecycle.outcomes import CONSTRUCTIVE_ACTIONS, DEFENSIVE_ACTIONS


def _grade(action: TradeAction, r_at: float, final: float) -> AdviceGrade:
    return AdviceGrade(
        trade_uid="uid",
        symbol="TEST",
        evaluated_at=None,
        action=action,
        r_at_evaluation=r_at,
        final_r=final,
        remaining_r=final - r_at,
        verdict=grade_advice(action, r_at, final),
    )


def test_every_action_is_classified() -> None:
    assert DEFENSIVE_ACTIONS | CONSTRUCTIVE_ACTIONS == frozenset(TradeAction)
    assert not DEFENSIVE_ACTIONS & CONSTRUCTIVE_ACTIONS


def test_exit_before_a_drop_is_correct() -> None:
    # advised Exit at +0.5R; the trade closed at -1R — exiting saved 1.5R
    assert grade_advice(TradeAction.EXIT, 0.5, -1.0) is AdviceVerdict.CORRECT


def test_exit_before_a_run_is_incorrect() -> None:
    # advised Exit at +0.5R; the trade closed at +3R — exiting left 2.5R behind
    assert grade_advice(TradeAction.EXIT, 0.5, 3.0) is AdviceVerdict.INCORRECT


def test_hold_through_a_run_is_correct() -> None:
    assert grade_advice(TradeAction.HOLD, 0.5, 3.0) is AdviceVerdict.CORRECT


def test_hold_into_a_drop_is_incorrect() -> None:
    assert grade_advice(TradeAction.HOLD, 0.5, -1.0) is AdviceVerdict.INCORRECT


def test_scale_in_before_gains_is_correct() -> None:
    assert grade_advice(TradeAction.SCALE_IN, 1.0, 4.0) is AdviceVerdict.CORRECT


def test_scale_out_before_a_fade_is_correct() -> None:
    assert grade_advice(TradeAction.SCALE_OUT, 2.0, 0.5) is AdviceVerdict.CORRECT


def test_raise_stop_is_defensive() -> None:
    assert grade_advice(TradeAction.RAISE_STOP, 1.5, 0.0) is AdviceVerdict.CORRECT
    assert grade_advice(TradeAction.RAISE_STOP, 1.5, 4.0) is AdviceVerdict.INCORRECT


def test_lower_stop_is_constructive() -> None:
    assert grade_advice(TradeAction.LOWER_STOP, 0.2, 2.0) is AdviceVerdict.CORRECT
    assert grade_advice(TradeAction.LOWER_STOP, 0.2, -1.0) is AdviceVerdict.INCORRECT


def test_small_moves_are_unclear() -> None:
    assert grade_advice(TradeAction.EXIT, 1.0, 1.1) is AdviceVerdict.UNCLEAR
    assert grade_advice(TradeAction.HOLD, 1.0, 0.9) is AdviceVerdict.UNCLEAR


def test_band_is_configurable() -> None:
    assert grade_advice(TradeAction.HOLD, 0.0, 0.4, unclear_band_r=0.5) is AdviceVerdict.UNCLEAR
    assert grade_advice(TradeAction.HOLD, 0.0, 0.4, unclear_band_r=0.1) is AdviceVerdict.CORRECT


def test_summary_aggregates_per_action() -> None:
    grades = [
        _grade(TradeAction.EXIT, 0.5, -1.0),  # correct
        _grade(TradeAction.EXIT, 0.5, 3.0),  # incorrect
        _grade(TradeAction.HOLD, 0.0, 2.0),  # correct
        _grade(TradeAction.HOLD, 0.0, 0.1),  # unclear
    ]
    stats = {s.action: s for s in advice_summary(grades)}
    assert set(stats) == {TradeAction.EXIT, TradeAction.HOLD}
    exit_stats = stats[TradeAction.EXIT]
    assert (exit_stats.n, exit_stats.correct, exit_stats.incorrect) == (2, 1, 1)
    assert exit_stats.accuracy == 0.5
    hold_stats = stats[TradeAction.HOLD]
    assert (hold_stats.correct, hold_stats.unclear) == (1, 1)
    assert hold_stats.accuracy == 1.0  # unclear is excluded from accuracy


def test_overall_accuracy_excludes_unclear() -> None:
    grades = [
        _grade(TradeAction.EXIT, 0.5, -1.0),  # correct
        _grade(TradeAction.HOLD, 0.0, 0.1),  # unclear
        _grade(TradeAction.HOLD, 0.0, -2.0),  # incorrect
    ]
    assert overall_accuracy(grades) == 0.5
    assert overall_accuracy([]) is None
    assert overall_accuracy([_grade(TradeAction.HOLD, 0.0, 0.1)]) is None


def test_to_dict_serializable() -> None:
    d = _grade(TradeAction.EXIT, 0.5, -1.0).to_dict()
    assert d["action"] == "Exit"
    assert d["verdict"] == "Correct"
    assert d["remaining_r"] == -1.5
