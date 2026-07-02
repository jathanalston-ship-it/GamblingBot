"""Automatic trade management: act when price reaches the stop or a target.

Pure decision logic. Given a trade's plan (entry / protective stop / scale-out
targets, with which targets have already been hit) and the freshest price,
:func:`decide_management` returns at most one :class:`ManagementDecision`:

1. **Stop loss** — price at/through the stop → close the full position.
   Risk is honoured first, always.
2. **Final target** — price at/above the last target → close the remainder.
3. **Intermediate target** — price at/above an unhit earlier target → scale out
   a configured fraction of the ORIGINAL position (fires once per target).

Every decision carries a plain-language, data-only ``analysis`` — the "how and
why" report — built from the numbers that triggered it (no speculation). The
service layer (``api/trade_lifecycle_service``) executes the decision against
the linked paper trade and persists the report, alert and audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from momentum.trade_lifecycle.config import TradeLifecycleConfig
from momentum.trade_lifecycle.types import ThesisEvaluation

STOP_LOSS = "stop_loss"
TAKE_PROFIT_SCALE = "take_profit_scale"
TAKE_PROFIT_FINAL = "take_profit_final"


@dataclass(frozen=True, slots=True)
class TargetState:
    """One plan target: its level and whether it has already been taken."""

    price: float
    r: float | None = None
    hit: bool = False


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
        out.append(
            TargetState(
                price=float(price),
                r=float(r) if isinstance(r, (int, float)) else None,
                hit=bool(item.get("hit", False)),
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
) -> ManagementDecision | None:
    """The one action (or none) warranted at ``price``. Long-only, like the platform."""
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

    # 1. Protective stop — risk first, regardless of any target.
    if config.auto_close_on_stop and price <= stop_price:
        reason = f"stop loss: {symbol} traded {price:.2f}, at/through the stop {stop_price:.2f}"
        analysis = (
            f"{symbol} closed on its protective stop. Price reached {price:.2f}, at or "
            f"through the stop at {stop_price:.2f} set against the {entry_price:.2f} entry "
            f"({_fmt_r(r_now)} at the close). The stop is the trade's pre-committed maximum "
            f"loss; honouring it caps the downside at roughly the planned risk.{context}"
        )
        return ManagementDecision(
            kind=STOP_LOSS,
            price=price,
            fraction=1.0,
            exit_reason="stop",
            target_index=None,
            reason=reason,
            analysis=analysis,
            evidence=evidence,
        )

    if not config.auto_take_profit or not targets:
        return None

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

    # 3. First unhit intermediate target — bank a slice, let the rest run.
    for index, target in enumerate(targets[:final_index]):
        if target.hit or price < target.price:
            continue
        fraction = config.target_scale_out_fraction
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
