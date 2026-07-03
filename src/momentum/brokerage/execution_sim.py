"""Execution simulator — realistic fills, never midpoint fantasies.

Pure: a :class:`Quote` (built from the freshest bar or a live print) plus an
order in, a :class:`SimulatedExecution` out. Market orders cross the spread —
a buy pays the ask, a sell hits the bid — then pay additional slippage that
grows with the order's share of available volume, widened at the open/close
and for option instruments, all scaled by the configured realism level
(``basic`` = frictionless, ``realistic`` = modeled, ``pessimistic`` = doubled).
Large orders relative to the bar's volume fill **partially** per tick.

The spread itself is estimated when only bar data is available: a base
spread in bps, widened by the bar's realized range (volatile names quote
wider) and by illiquidity (thin names quote wider).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from momentum.brokerage.config import ExecutionSimConfig, RealismLevel
from momentum.core.enums import InstrumentType, Side

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class Quote:
    """The market as the simulator sees it at one instant.

    Built from a real bid/ask when available; otherwise estimated from the
    freshest bar via :func:`quote_from_bar` (the estimate is explicit —
    ``estimated=True`` — never silently assumed).
    """

    symbol: str
    ts: dt.datetime
    bid: float
    ask: float
    last: float
    volume: float  # bar volume the order can participate in
    day_range_pct: float = 0.0  # (high-low)/close of the source bar
    estimated: bool = True

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)


def quote_from_bar(
    symbol: str,
    *,
    ts: dt.datetime,
    close: float,
    volume: float,
    high: float | None = None,
    low: float | None = None,
    config: ExecutionSimConfig,
    instrument: InstrumentType = InstrumentType.SHARES,
) -> Quote:
    """Estimate a two-sided quote from bar data (spread model, not midpoint)."""
    day_range = ((high - low) / close) if (high is not None and low is not None and close) else 0.0
    spread_bps = config.base_spread_bps * (1.0 + config.volatility_spread_factor * day_range)
    if instrument.is_option:
        spread_bps *= config.option_spread_multiplier
    half = max(close * spread_bps / 10_000.0, config.min_spread_cents / 100.0) / 2.0
    return Quote(
        symbol=symbol.upper(),
        ts=ts,
        bid=max(close - half, 0.01),
        ask=close + half,
        last=close,
        volume=max(volume, 0.0),
        day_range_pct=max(day_range, 0.0),
        estimated=True,
    )


@dataclass(frozen=True, slots=True)
class SimulatedExecution:
    """One tick's execution result: what filled, at what price, and why."""

    quantity: int  # shares/contracts filled this tick (0 = nothing yet)
    price: float
    fees: float
    partial: bool  # True when liquidity capped the fill below the request
    reason: str  # data-only story: spread crossed, slippage applied, ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "price": round(self.price, 4),
            "fees": round(self.fees, 2),
            "partial": self.partial,
            "reason": self.reason,
        }


def time_of_day_factor(ts: dt.datetime, config: ExecutionSimConfig) -> float:
    """Frictions are worst in the first/last 30 minutes, calmer midday."""
    local = ts.astimezone(_ET)
    minutes = local.hour * 60 + local.minute
    open_m, close_m = 9 * 60 + 30, 16 * 60
    if open_m <= minutes < open_m + 30 or close_m - 30 <= minutes < close_m:
        return config.open_close_penalty
    if 11 * 60 <= minutes < 14 * 60:
        return config.midday_discount
    return 1.0


class ExecutionSimulator:
    """Fill engine for the paper venue (pure; injectable into the brokerage)."""

    def __init__(self, config: ExecutionSimConfig) -> None:
        self.config = config

    def execute(
        self,
        *,
        side: Side,
        quantity: int,
        quote: Quote,
        instrument: InstrumentType = InstrumentType.SHARES,
        limit_price: float | None = None,
    ) -> SimulatedExecution:
        """Fill (part of) an order against the quote.

        ``limit_price`` caps the executable price (a limit or stop-limit leg);
        market/stop orders pass ``None`` and accept the modeled price.
        """
        cfg = self.config
        friction = cfg.realism.friction_multiplier

        if cfg.realism is RealismLevel.BASIC:
            price = quote.last
            return SimulatedExecution(
                quantity=quantity,
                price=price,
                fees=self._fees(quantity),
                partial=False,
                reason="basic realism: filled at the last print, no frictions",
            )

        # 1. Cross the spread: buys pay the ask, sells hit the bid. Never the mid.
        price = quote.ask if side is Side.LONG else quote.bid
        parts = [
            f"crossed the spread ({quote.bid:.2f}/{quote.ask:.2f}"
            + (", estimated from the bar)" if quote.estimated else ")")
        ]

        # 2. Liquidity: how much of the bar's volume is this order?
        available = max(quote.volume, 1.0)
        max_fill = max(int(available * cfg.partial_fill_participation), 1)
        fill_qty = min(quantity, max_fill)
        partial = fill_qty < quantity
        if partial:
            parts.append(
                f"liquidity capped the tick at {fill_qty}/{quantity} "
                f"({cfg.partial_fill_participation:.0%} of {available:,.0f} volume)"
            )

        # 3. Slippage: participation-driven price impact, worse when illiquid,
        #    at the open/close, and under pessimistic realism.
        participation = fill_qty / available
        slip_bps = cfg.slippage_participation_bps * participation * 100.0
        slip_bps *= 1.0 + cfg.illiquidity_spread_factor * participation
        slip_bps *= time_of_day_factor(quote.ts, cfg)
        slip_bps *= friction
        slip = price * slip_bps / 10_000.0
        price = price + slip if side is Side.LONG else price - slip
        if slip > 0:
            parts.append(f"slippage {slip_bps:.1f}bps for {participation:.2%} participation")

        # 4. A limit caps the price: if the modeled price breaches it, fill AT
        #    the limit (the book would have queued us there).
        if limit_price is not None:
            if side is Side.LONG and price > limit_price:
                price = limit_price
                parts.append("capped at the limit price")
            elif side is Side.SHORT and price < limit_price:
                price = limit_price
                parts.append("floored at the limit price")

        return SimulatedExecution(
            quantity=fill_qty,
            price=max(price, 0.01),
            fees=self._fees(fill_qty),
            partial=partial,
            reason="; ".join(parts),
        )

    def _fees(self, quantity: int) -> float:
        fee = quantity * self.config.fee_per_share
        return max(fee, self.config.min_fee) if fee > 0 else self.config.min_fee
