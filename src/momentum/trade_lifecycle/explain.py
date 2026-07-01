"""Explainability engine — why the recommendation is what it is (pure).

Every reevaluation ships a structured explanation built **only from measured
values already computed** (conviction, trends, health components, the prior
evaluation's readings): what changed, why it changed, why confidence moved,
the evidence for the recommendation and the evidence against it, plus a
narrative capped at 250 words. Deterministic templating over real numbers —
nothing is invented.
"""

from __future__ import annotations

from typing import Any

from momentum.trade_lifecycle.health import TradeHealthScore
from momentum.trade_lifecycle.types import (
    EvaluationInputs,
    PriorSnapshot,
    TradeAction,
    Trend,
)

MAX_NARRATIVE_WORDS = 250

# A change smaller than this (in points) is reported as "unchanged".
_POINT_BAND = 1.0


def _cap_words(text: str, limit: int = MAX_NARRATIVE_WORDS) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit])


def _what_changed(
    inputs: EvaluationInputs,
    health: TradeHealthScore,
    action: TradeAction,
    prior: PriorSnapshot | None,
) -> list[str]:
    changes: list[str] = []
    if prior is None:
        changes.append("first evaluation — baseline recorded, no prior to compare")
        return changes
    if prior.price is not None and prior.price > 0:
        move = (inputs.price - prior.price) / prior.price * 100.0
        if abs(move) >= 0.5:
            changes.append(f"price moved {move:+.1f}% ({prior.price:.2f} → {inputs.price:.2f})")
    if prior.conviction is not None and inputs.current_conviction is not None:
        delta = inputs.current_conviction - prior.conviction
        if abs(delta) >= _POINT_BAND:
            changes.append(
                f"conviction {prior.conviction:.0f} → {inputs.current_conviction:.0f} ({delta:+.0f})"
            )
    if prior.health_score is not None:
        delta = health.score - prior.health_score
        if abs(delta) >= _POINT_BAND:
            changes.append(f"health {prior.health_score:.0f} → {health.score:.0f} ({delta:+.0f})")
    if prior.action is not None and prior.action != action.value:
        changes.append(f"recommendation changed: {prior.action} → {action.value}")
    if not changes:
        changes.append("no material change since the last evaluation")
    return changes


def _why_changed(health: TradeHealthScore) -> list[str]:
    """The components that moved the score most, quoted with their evidence."""
    ranked = sorted(health.components, key=lambda c: abs(c.delta), reverse=True)
    return [
        f"{c.name.replace('_', ' ')} {c.delta:+.1f} pts: {c.detail}"
        for c in ranked[:3]
        if abs(c.delta) >= 0.5
    ] or ["every component is near neutral — no single driver"]


def _confidence(health: TradeHealthScore, prior: PriorSnapshot | None) -> dict[str, str]:
    if prior is None or prior.health_score is None:
        return {
            "direction": "baseline",
            "reason": f"first reading — health starts at {health.score:.0f}/100",
        }
    delta = health.score - prior.health_score
    if abs(delta) < _POINT_BAND:
        return {
            "direction": "unchanged",
            "reason": f"health steady at {health.score:.0f}/100 ({delta:+.1f} pts)",
        }
    direction = "increased" if delta > 0 else "decreased"
    movers = sorted(health.components, key=lambda c: abs(c.delta), reverse=True)
    top = movers[0]
    return {
        "direction": direction,
        "reason": (
            f"health {direction} {abs(delta):.1f} pts to {health.score:.0f}/100; "
            f"largest factor: {top.name.replace('_', ' ')} ({top.detail})"
        ),
    }


def _evidence(health: TradeHealthScore) -> tuple[list[str], list[str]]:
    supporting = [
        f"{c.name.replace('_', ' ')} (+{c.delta:.1f} pts): {c.detail}"
        for c in health.components
        if c.delta >= 0.5
    ]
    contradicting = [
        f"{c.name.replace('_', ' ')} ({c.delta:.1f} pts): {c.detail}"
        for c in health.components
        if c.delta <= -0.5
    ]
    return supporting, contradicting


def build_explanation(
    inputs: EvaluationInputs,
    *,
    health: TradeHealthScore,
    action: TradeAction,
    reasons: tuple[str, ...],
    momentum_trend: Trend,
    rs_trend: Trend,
) -> dict[str, Any]:
    """The structured, data-only explanation persisted with every evaluation."""
    prior = inputs.prior
    what = _what_changed(inputs, health, action, prior)
    why = _why_changed(health)
    confidence = _confidence(health, prior)
    supporting, contradicting = _evidence(health)

    narrative_parts = [
        f"{inputs.symbol.upper()}: {action.value} — {'; '.join(reasons)}.",
        f"Health {health.score:.0f}/100.",
        "What changed: " + "; ".join(what) + ".",
        "Drivers: " + "; ".join(why) + ".",
        f"Confidence {confidence['direction']}: {confidence['reason']}.",
    ]
    if supporting:
        narrative_parts.append("For: " + "; ".join(supporting) + ".")
    if contradicting:
        narrative_parts.append("Against: " + "; ".join(contradicting) + ".")
    narrative = _cap_words(" ".join(narrative_parts))

    return {
        "what_changed": what,
        "why_changed": why,
        "confidence": confidence,
        "supporting": supporting,
        "contradicting": contradicting,
        "narrative": narrative,
    }
