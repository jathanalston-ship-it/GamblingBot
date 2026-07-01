"""Grade reevaluation advice against realized trade outcomes (pure).

Once a tracked trade is linked to its executed journal trade and that trade
closes, every evaluation it received can be graded with hindsight: given the
R the trade was at when the advice was issued and the R it finally closed at,
was the recommended action right?

The rule is symmetric and deliberately simple:

* **Defensive** advice (Exit, Scale Out, Raise Stop) is correct when the trade
  subsequently *deteriorated* (the R still to come was negative) and incorrect
  when the trade kept climbing.
* **Constructive** advice (Hold, Scale In, Lower Stop) is correct when the
  trade subsequently *improved* and incorrect when it deteriorated.
* Moves inside ``±unclear_band_r`` are **Unclear** — too small to credit or
  blame the advice.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any

from momentum.trade_lifecycle.types import TradeAction

DEFENSIVE_ACTIONS = frozenset({TradeAction.EXIT, TradeAction.SCALE_OUT, TradeAction.RAISE_STOP})
CONSTRUCTIVE_ACTIONS = frozenset({TradeAction.HOLD, TradeAction.SCALE_IN, TradeAction.LOWER_STOP})

# Post-advice moves smaller than this (in R) neither credit nor blame the advice.
DEFAULT_UNCLEAR_BAND_R = 0.25


class AdviceVerdict(str, Enum):
    """Hindsight grade of one piece of advice."""

    CORRECT = "Correct"
    INCORRECT = "Incorrect"
    UNCLEAR = "Unclear"


@dataclass(frozen=True, slots=True)
class AdviceGrade:
    """One evaluation's advice graded against the trade's realized outcome."""

    trade_uid: str
    symbol: str
    evaluated_at: str | None
    action: TradeAction
    r_at_evaluation: float
    final_r: float
    remaining_r: float  # final_r - r_at_evaluation: what happened after the advice
    verdict: AdviceVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_uid": self.trade_uid,
            "symbol": self.symbol,
            "evaluated_at": self.evaluated_at,
            "action": self.action.value,
            "r_at_evaluation": round(self.r_at_evaluation, 4),
            "final_r": round(self.final_r, 4),
            "remaining_r": round(self.remaining_r, 4),
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class AdviceActionStats:
    """Aggregate hindsight accuracy for one action."""

    action: TradeAction
    n: int
    correct: int
    incorrect: int
    unclear: int
    accuracy: float | None  # correct / (correct + incorrect); None if nothing decisive
    avg_remaining_r: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "n": self.n,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "unclear": self.unclear,
            "accuracy": round(self.accuracy, 4) if self.accuracy is not None else None,
            "avg_remaining_r": (
                round(self.avg_remaining_r, 4) if self.avg_remaining_r is not None else None
            ),
        }


def grade_advice(
    action: TradeAction,
    r_at_evaluation: float,
    final_r: float,
    *,
    unclear_band_r: float = DEFAULT_UNCLEAR_BAND_R,
) -> AdviceVerdict:
    """Was the advice right, given what the trade did afterwards?"""
    remaining = final_r - r_at_evaluation
    if abs(remaining) <= unclear_band_r:
        return AdviceVerdict.UNCLEAR
    deteriorated = remaining < 0
    if action in DEFENSIVE_ACTIONS:
        return AdviceVerdict.CORRECT if deteriorated else AdviceVerdict.INCORRECT
    return AdviceVerdict.INCORRECT if deteriorated else AdviceVerdict.CORRECT


def advice_summary(grades: list[AdviceGrade]) -> list[AdviceActionStats]:
    """Per-action hindsight stats, in the enum's declaration order."""
    by_action: dict[TradeAction, list[AdviceGrade]] = defaultdict(list)
    for grade in grades:
        by_action[grade.action].append(grade)

    stats: list[AdviceActionStats] = []
    for action in TradeAction:
        cohort = by_action.get(action, [])
        if not cohort:
            continue
        correct = sum(1 for g in cohort if g.verdict is AdviceVerdict.CORRECT)
        incorrect = sum(1 for g in cohort if g.verdict is AdviceVerdict.INCORRECT)
        unclear = len(cohort) - correct - incorrect
        decisive = correct + incorrect
        stats.append(
            AdviceActionStats(
                action=action,
                n=len(cohort),
                correct=correct,
                incorrect=incorrect,
                unclear=unclear,
                accuracy=correct / decisive if decisive else None,
                avg_remaining_r=sum(g.remaining_r for g in cohort) / len(cohort),
            )
        )
    return stats


def overall_accuracy(grades: list[AdviceGrade]) -> float | None:
    """Correct / decisive across all actions (None when nothing is decisive)."""
    correct = sum(1 for g in grades if g.verdict is AdviceVerdict.CORRECT)
    incorrect = sum(1 for g in grades if g.verdict is AdviceVerdict.INCORRECT)
    decisive = correct + incorrect
    return correct / decisive if decisive else None
