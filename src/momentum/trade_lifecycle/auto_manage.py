"""Automatic trade management: act when price reaches the stop or a target.

Pure decision logic. Given a trade's plan (entry / protective stop / scale-out
targets, with which targets have already been hit) and the freshest price,
:func:`decide_management` returns at most one :class:`ManagementDecision`:

1. **Stop loss** — price at/through the stop → close the full position.
   Risk is honoured first, always.
2. **Final target** — price at/above the last target → close the remainder.
3. **Intermediate target** — price at/above an unhit earlier target → scale out
   the plan's fraction of the ORIGINAL position for that target (fires once per
   target; falls back to ``target_scale_out_fraction`` for legacy rows).
4. **Breakeven stop raise** — once the trade shows ``raise_stop_gain_r`` of open
   profit and the working stop is still below entry, the stop ratchets to
   breakeven — the "Raise Stop" advice, executed. Risk-reducing only.

Every decision carries a plain-language, data-only ``analysis`` — the "how and
why" report — built from the numbers that triggered it (no speculation). The
service layer (``api/trade_lifecycle_service``) executes the decision against
the linked paper trade and persists the report, alert and audit trail.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from momentum.trade_lifecycle.config import TradeLifecycleConfig
from momentum.trade_lifecycle.types import ThesisEvaluation

STOP_LOSS = "stop_loss"
TAKE_PROFIT_SCALE = "take_profit_scale"
TAKE_PROFIT_FINAL = "take_profit_final"
RAISE_STOP = "raise_stop"


@dataclass(frozen=True, slots=True)
class TargetState:
    """One plan target: its level and whether it has already been taken."""

    price: float
    r: float | None = None
    hit: bool = False
    fraction: float | None = None  # the plan's scale-out fraction for this target


@dataclass(frozen=True, slots=True)
class ManagementDecision:
    """One action the system takes on an open trade, with its full rationale."""

    kind: str  # STOP_LOSS | TAKE_PROFIT_SCALE | TAKE_PROFIT_FINAL
    price: float
    fraction: float  # of the ORIGINAL position (1.0 = close everything open)
    exit_reason: str  # journal exit_reason: "stop" | "target" | "scale_out"
    target_index: int | None  # which target fired (None for stop)
    reason: str  # one-line summary
    analysis: str  # the data-only "how and why" report
    evidence: dict[str, Any]  # the numbers behind the decision

    @property
    def closes_position(self) -> bool:
        return self.kind in (STOP_LOSS, TAKE_PROFIT_FINAL)

    @property
    def adjusts_stop(self) -> bool:
        return self.kind == RAISE_STOP

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "price": self.price,
            "fraction": self.fraction,
            "exit_reason": self.exit_reason,
            "target_index": self.target_index,
            "reason": self.reason,
            "analysis": self.analysis,
            "evidence": self.evidence,
        }


def targets_from_records(records: Any) -> tuple[TargetState, ...]:
    """Parse the tracked trade's ``targets`` JSON into :class:`TargetState`s."""
    if not isinstance(records, (list, tuple)):
        return ()
    out: list[TargetState] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        r = item.get("r", item.get("r_multiple"))  # trade plans persist "r_multiple"
        frac = item.get("scale_out_pct")
        out.append(
            TargetState(
                price=float(price),
                r=float(r) if isinstance(r, (int, float)) else None,
                hit=bool(item.get("hit", False)),
                fraction=(float(frac) if isinstance(frac, (int, float)) and 0 < frac < 1 else None),
            )
        )
    return tuple(out)


def _r_at(price: float, entry: float, stop: float) -> float | None:
    """Per-share R of ``price`` given the ORIGINAL entry/stop (long)."""
    risk = entry - stop
    if risk <= 0:
        return None
    return (price - entry) / risk


def _fmt_r(r: float | None) -> str:
    return f"{r:+.2f}R" if r is not None else "n/a"


def decide_management(
    *,
    symbol: str,
    entry_price: float,
    stop_price: float,
    price: float,
    targets: tuple[TargetState, ...],
    evaluation: ThesisEvaluation | None,
    days_held: float,
    config: TradeLifecycleConfig,
    current_stop: float | None = None,
) -> ManagementDecision | None:
    """The one action (or none) warranted at ``price``. Long-only, like the platform.

    ``current_stop`` is the working stop when it has been raised (execution
    state on the linked paper trade); breach is judged against the tighter of
    the two, while R is always measured against the ORIGINAL entry/stop risk.
    """
    working_stop = max(stop_price, current_stop) if current_stop is not None else stop_price
    r_now = _r_at(price, entry_price, stop_price)
    context = _context(evaluation, days_held)
    evidence: dict[str, Any] = {
        "symbol": symbol,
        "entry_price": round(entry_price, 4),
        "stop_price": round(stop_price, 4),
        "price": round(price, 4),
        "r_at_price": round(r_now, 3) if r_now is not None else None,
        "days_held": round(days_held, 1),
    }

    # 1. Protective stop — risk first, regardless of any target. A raised
    #    (breakeven) stop protects banked gains the same way.
    if config.auto_close_on_stop and price <= working_stop:
        raised = working_stop > stop_price
        reason = f"stop loss: {symbol} traded {price:.2f}, at/through the stop {working_stop:.2f}"
        analysis = (
            f"{symbol} closed on its protective stop. Price reached {price:.2f}, at or "
            f"through the {'raised (breakeven) ' if raised else ''}stop at {working_stop:.2f} "
            f"set against the {entry_price:.2f} entry ({_fmt_r(r_now)} at the close). The stop "
            f"is the trade's pre-committed maximum loss; honouring it caps the downside at "
            f"roughly the planned risk.{context}"
        )
        return ManagementDecision(
            kind=STOP_LOSS,
            price=price,
            fraction=1.0,
            exit_reason="stop",
            target_index=None,
            reason=reason,
            analysis=analysis,
            evidence={**evidence, "working_stop": round(working_stop, 4)},
        )

    take_profit = config.auto_take_profit and bool(targets)

    if take_profit:
        decision = _target_decision(
            symbol=symbol,
            entry_price=entry_price,
            price=price,
            r_now=r_now,
            targets=targets,
            context=context,
            evidence=evidence,
            config=config,
        )
        if decision is not None:
            return decision

    # 4. Breakeven ratchet — "Raise Stop" advice, executed. Only ever tightens.
    if (
        config.auto_raise_stop_to_breakeven
        and r_now is not None
        and r_now >= config.raise_stop_gain_r
        and working_stop < entry_price
    ):
        reason = (
            f"stop raised to breakeven: {symbol} shows {_fmt_r(r_now)} open profit "
            f"(threshold {config.raise_stop_gain_r:.1f}R)"
        )
        analysis = (
            f"{symbol} reached {_fmt_r(r_now)} of open profit, past the "
            f"{config.raise_stop_gain_r:.1f}R threshold, while the working stop "
            f"({working_stop:.2f}) was still below the {entry_price:.2f} entry. The stop was "
            f"raised to breakeven so the trade can no longer turn into a loss — risk is "
            f"reduced without capping the upside.{context}"
        )
        return ManagementDecision(
            kind=RAISE_STOP,
            price=entry_price,  # the new stop level
            fraction=0.0,
            exit_reason="",
            target_index=None,
            reason=reason,
            analysis=analysis,
            evidence={**evidence, "working_stop": round(working_stop, 4)},
        )

    return None


def _target_decision(
    *,
    symbol: str,
    entry_price: float,
    price: float,
    r_now: float | None,
    targets: tuple[TargetState, ...],
    context: str,
    evidence: dict[str, Any],
    config: TradeLifecycleConfig,
) -> ManagementDecision | None:

    # 2. Final target — the plan is complete: close what remains.
    final_index = len(targets) - 1
    final = targets[final_index]
    if price >= final.price:
        reason = (
            f"take profit: {symbol} reached the final target {final.price:.2f} (traded {price:.2f})"
        )
        analysis = (
            f"{symbol} reached the plan's final target. Price traded {price:.2f}, at or above "
            f"target {final_index + 1} of {len(targets)} at {final.price:.2f} "
            f"({_fmt_r(final.r)} planned, {_fmt_r(r_now)} at the close). The remaining "
            f"position was closed because the plan's profit objectives are fully met; "
            f"holding beyond the final target would be an unplanned trade.{context}"
        )
        return ManagementDecision(
            kind=TAKE_PROFIT_FINAL,
            price=price,
            fraction=1.0,
            exit_reason="target",
            target_index=final_index,
            reason=reason,
            analysis=analysis,
            evidence={**evidence, "target_price": round(final.price, 4)},
        )

    # 3. First unhit intermediate target — bank the PLAN'S slice for that
    #    target, let the rest run (config fraction only for legacy rows).
    for index, target in enumerate(targets[:final_index]):
        if target.hit or price < target.price:
            continue
        fraction = (
            target.fraction if target.fraction is not None else config.target_scale_out_fraction
        )
        reason = (
            f"partial take profit: {symbol} reached target {index + 1} "
            f"at {target.price:.2f} (traded {price:.2f})"
        )
        analysis = (
            f"{symbol} reached target {index + 1} of {len(targets)} at {target.price:.2f} "
            f"({_fmt_r(target.r)} planned, {_fmt_r(r_now)} at the fill). Per the plan, "
            f"{fraction:.0%} of the original position was sold to bank the gain while the "
            f"remainder stays on to capture further trend — the positive-skew objective "
            f"keeps runners running rather than cashing out whole positions early.{context}"
        )
        return ManagementDecision(
            kind=TAKE_PROFIT_SCALE,
            price=price,
            fraction=fraction,
            exit_reason="scale_out",
            target_index=index,
            reason=reason,
            analysis=analysis,
            evidence={**evidence, "target_price": round(target.price, 4)},
        )

    return None


def _context(evaluation: ThesisEvaluation | None, days_held: float) -> str:
    """Thesis context at the moment of the decision (data-only, from the evaluation)."""
    if evaluation is None:
        return ""
    bits = [f"health {evaluation.health.value} ({evaluation.health_score:.0f}/100)"]
    if evaluation.current_conviction is not None:
        delta = (
            f" ({evaluation.conviction_delta:+.0f} vs entry)"
            if evaluation.conviction_delta is not None
            else ""
        )
        bits.append(f"conviction {evaluation.current_conviction:.0f}{delta}")
    bits.append(f"held {days_held:.0f}d")
    return f" At the decision the thesis read: {', '.join(bits)}."


def sector_concentration(
    sectors: Sequence[str | None],
    *,
    warn_share: float,
    min_positions: int,
) -> tuple[str, float, int] | None:
    """Detect a crowded book: one sector holding >= ``warn_share`` of the open
    positions (only meaningful from ``min_positions`` trades). Returns
    ``(sector, share, count)`` or ``None`` when the book is diversified.

    Correlation is guarded at ENTRY by the risk engine; this watches the book
    as it evolves — winners in one theme can concentrate a once-diverse book.
    """
    named = [s for s in sectors if s]
    if len(named) < min_positions:
        return None
    sector, count = Counter(named).most_common(1)[0]
    share = count / len(named)
    if share >= warn_share:
        return sector, share, count
    return None
