"""Pure shadow-trade logic: expected fills and per-scan management.

Expected fills reuse the venue's :class:`ExecutionSimulator` (spread
crossed, participation slippage — never a midpoint fantasy) against a
quote estimated from the live bar. Management mirrors the platform's
rules: protective stop first, then the plan target, then a breakeven
raise once the trade shows enough open profit. All pure — no I/O.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from momentum.brokerage.config import default_config as brokerage_default_config
from momentum.brokerage.execution_sim import ExecutionSimulator, quote_from_bar
from momentum.core.enums import Side
from momentum.shadow.config import ShadowConfig


@dataclass(frozen=True, slots=True)
class ExpectedFill:
    """What the order would have cost, and how far from the reference."""

    price: float
    reference: float
    slippage_bps: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": round(self.price, 4),
            "reference": round(self.reference, 4),
            "slippage_bps": round(self.slippage_bps, 2),
        }


def expected_fill(
    *,
    symbol: str,
    side: Side,
    quantity: int,
    ts: dt.datetime,
    close: float,
    volume: float,
    high: float | None = None,
    low: float | None = None,
) -> ExpectedFill:
    """Model the fill the order would get against this bar's estimated quote."""
    config = brokerage_default_config().execution
    quote = quote_from_bar(
        symbol, ts=ts, close=close, volume=volume, high=high, low=low, config=config
    )
    execution = ExecutionSimulator(config).execute(side=side, quantity=quantity, quote=quote)
    slippage = (
        (execution.price - close) / close * 10_000.0
        if side is Side.LONG
        else (close - execution.price) / close * 10_000.0
    )
    return ExpectedFill(price=execution.price, reference=close, slippage_bps=slippage)


@dataclass(frozen=True, slots=True)
class ShadowAction:
    """The one management action a scan warrants for an open shadow trade."""

    kind: str  # close_stop | close_target | raise_stop | none
    exit_reason: str | None = None
    new_stop: float | None = None

    @property
    def closes(self) -> bool:
        return self.kind in ("close_stop", "close_target")


def manage_shadow_trade(
    *,
    price: float,
    entry: float,
    stop: float,
    current_stop: float | None,
    target: float | None,
    config: ShadowConfig | None = None,
) -> ShadowAction:
    """Stop first, then target, then the breakeven ratchet. Pure, long-only."""
    cfg = config or ShadowConfig()
    working_stop = max(stop, current_stop) if current_stop is not None else stop

    if price <= working_stop:
        return ShadowAction(kind="close_stop", exit_reason="stop")
    if target is not None and price >= target:
        return ShadowAction(kind="close_target", exit_reason="target")

    risk = entry - stop
    if risk > 0 and working_stop < entry:
        r_now = (price - entry) / risk
        if r_now >= cfg.raise_stop_gain_r:
            return ShadowAction(kind="raise_stop", new_stop=entry)
    return ShadowAction(kind="none")
