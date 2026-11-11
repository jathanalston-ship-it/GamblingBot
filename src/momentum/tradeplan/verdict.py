"""Trade-plan verdict — BUY / WATCH / WAIT / AVOID, graded by the strategy's rules.

Pure: the service layer gathers stored evidence (scan row, the market gate,
the trade plan, freshness, liquidity, earnings) into :class:`VerdictInputs`;
this module applies the strategy's own conditions (:mod:`momentum.strategy`)
and returns a verdict that **never simply says no** — every WAIT names exactly
what to wait for, every AVOID names why, and every verdict carries the decision
explainer. BUY means precisely "this is a signal the backtested rules would
take today": the stock passes the entry rules on the active scan, the market
gate is open, the data is fresh and a plan exists. Conviction is reported as
context; it does not gate the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BUY = "BUY"
WATCH = "WATCH"
WAIT = "WAIT"
AVOID = "AVOID"

MIN_DOLLAR_VOLUME = 5_000_000.0  # below this, fills are fantasy


@dataclass(frozen=True, slots=True)
class VerdictInputs:
    symbol: str
    price: float | None
    conviction_score: float | None
    conviction_band: str | None
    previous_conviction: float | None  # the prior scan's score (why-not-yesterday)
    conviction_explanation: str | None
    top_factors: tuple[str, ...] = ()  # strongest conviction components, named
    weak_factors: tuple[str, ...] = ()  # weakest components, named
    momentum_score: float | None = None
    relative_volume: float | None = None
    dollar_volume: float | None = None
    atr: float | None = None
    sector: str | None = None
    sector_rs: float | None = None
    regime: str | None = None  # bullish | neutral | bearish
    regime_confidence: float | None = None
    data_stale: bool = False
    days_to_earnings: int | None = None
    earnings_block_days: int = 0
    # The plan (when one exists).
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    reward_risk: float | None = None
    suggested_shares: int | None = None
    expected_hold_days: tuple[int | None, int | None] = (None, None)
    stop_basis: str | None = None  # e.g. "1.8x ATR under the 20EMA"
    target_basis: str | None = None
    size_basis: str | None = None
    failure_conditions: tuple[str, ...] = ()
    instrument_verdict: str | None = None  # "Leverage Eligible" | "Shares Preferred"
    instrument_reasons: tuple[str, ...] = ()
    # The strategy's own facts (momentum.strategy).
    market_uptrend: bool | None = None  # the market gate; None = not measured
    is_current_signal: bool = True  # on the active scan's candidate list
    bars_since_breakout: int | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    symbol: str
    verdict: str  # BUY | WATCH | WAIT | AVOID
    confidence: float | None
    reasons: tuple[str, ...]
    next_condition: str  # the highest-probability condition that changes the thesis
    explainer: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "next_condition": self.next_condition,
            "explainer": self.explainer,
        }


def _explainer(i: VerdictInputs) -> dict[str, Any]:
    conviction_move = None
    if i.conviction_score is not None and i.previous_conviction is not None:
        delta = i.conviction_score - i.previous_conviction
        direction = "rose" if delta > 0 else ("fell" if delta < 0 else "held")
        conviction_move = (
            f"Conviction {direction} from {i.previous_conviction:.0f} to "
            f"{i.conviction_score:.0f} since the previous scan"
        )
    why_now = [
        part
        for part in (
            conviction_move,
            (
                f"relative volume {i.relative_volume:.1f}x"
                if i.relative_volume is not None
                else None
            ),
            f"market regime {i.regime}" if i.regime else None,
            "data is scan-fresh" if not i.data_stale else "DATA IS STALE",
        )
        if part
    ]
    return {
        "why_this_trade": {
            "narrative": i.conviction_explanation,
            "strongest_factors": list(i.top_factors),
            "momentum_score": i.momentum_score,
            "sector": i.sector,
            "sector_rs": i.sector_rs,
        },
        "why_now": why_now,
        "why_not_yesterday": conviction_move
        or "no previous conviction on record — this is the first scan that surfaced it",
        "what_would_invalidate": list(i.failure_conditions)
        or ([f"a close below the stop at {i.stop:.2f}"] if i.stop else []),
        "what_would_improve": [
            "the stock making further new highs (the exit level rises with it)",
            "the market staying above its 200-day average",
        ],
        "what_would_reduce_conviction": list(i.weak_factors)
        + (["the market closing below its 200-day average"] if i.market_uptrend else []),
        "why_this_stop": i.stop_basis
        or (f"plan stop {i.stop:.2f} caps the loss at the structure level" if i.stop else None),
        "why_this_target": i.target_basis
        or (
            f"target {i.target:.2f} = {i.reward_risk:.1f}R against the stop"
            if i.target and i.reward_risk
            else None
        ),
        "why_this_size": i.size_basis
        or (
            f"{i.suggested_shares} shares keeps the stop-loss inside the per-trade risk budget"
            if i.suggested_shares
            else None
        ),
        "instrument": {
            "recommendation": i.instrument_verdict,
            "reasons": list(i.instrument_reasons),
        },
    }


def evaluate_verdict(i: VerdictInputs) -> Verdict:
    """Grade one symbol against the strategy's rules (an explicit ladder).

    A symbol only reaches this function with a scan row, i.e. it passed the
    strategy's entry rules on some scan. The ladder then asks, in order: is it
    tradeable at all (AVOID), is now the wrong moment (WAIT), and is it a live
    signal with a complete plan (BUY) — otherwise WATCH.
    """
    explainer = _explainer(i)

    # ---- AVOID: structural problems no timing fixes -------------------------
    if i.dollar_volume is not None and i.dollar_volume < MIN_DOLLAR_VOLUME:
        return Verdict(
            symbol=i.symbol,
            verdict=AVOID,
            confidence=i.conviction_score,
            reasons=(
                f"poor liquidity: ${i.dollar_volume / 1e6:.1f}M average dollar volume "
                f"(needs ${MIN_DOLLAR_VOLUME / 1e6:.0f}M+) — exits would move the price",
            ),
            next_condition=(
                f"sustained dollar volume above ${MIN_DOLLAR_VOLUME / 1e6:.0f}M/day would "
                "make the setup tradeable"
            ),
            explainer=explainer,
        )

    # ---- WAIT: a real signal, the wrong moment ------------------------------
    wait: list[str] = []
    next_condition = ""
    if i.data_stale:
        wait.append("market data is stale — wait for a fresh scan before pricing an entry")
        next_condition = "the next completed scan with fresh bars"
    if i.market_uptrend is False:
        wait.append(
            "the market is in a downtrend (SPY is below its 200-day average) — the "
            "strategy opens no new positions until it recovers"
        )
        next_condition = next_condition or "SPY closing back above its 200-day average"
    elif i.market_uptrend is None and not i.data_stale:
        wait.append("the market trend has not been measured yet — run a scan first")
        next_condition = next_condition or "a completed scan that measures the market trend"
    if (
        i.days_to_earnings is not None
        and i.earnings_block_days > 0
        and 0 <= i.days_to_earnings <= i.earnings_block_days
    ):
        wait.append(f"earnings in {i.days_to_earnings} day(s) — binary risk; wait for the report")
        next_condition = next_condition or "the earnings report clearing the binary risk"
    if wait:
        return Verdict(
            symbol=i.symbol,
            verdict=WAIT,
            confidence=i.conviction_score,
            reasons=tuple(wait),
            next_condition=next_condition,
            explainer=explainer,
        )

    # ---- BUY vs WATCH --------------------------------------------------------
    if not i.is_current_signal:
        return Verdict(
            symbol=i.symbol,
            verdict=WATCH,
            confidence=i.conviction_score,
            reasons=(
                "this stock passed the entry rules on an earlier scan but is not on "
                "today's signal list",
            ),
            next_condition=(
                "a new 50-day high while it stays in the top momentum group would "
                "put it back on the list"
            ),
            explainer=explainer,
        )
    if i.entry is None or i.stop is None:
        return Verdict(
            symbol=i.symbol,
            verdict=WATCH,
            confidence=i.conviction_score,
            reasons=("no complete trade plan yet — run a scan that surfaces it",),
            next_condition="a fresh scan that prices the entry and the stop",
            explainer=explainer,
        )
    rules = ["it passes every entry rule"]
    if i.momentum_score is not None:
        rules.append(f"momentum stronger than {i.momentum_score:.0f}% of the universe")
    if i.bars_since_breakout is not None:
        when = (
            "on the last session"
            if i.bars_since_breakout == 0
            else f"{i.bars_since_breakout} session(s) ago"
        )
        rules.append(f"new 50-day high {when}")
    rules.append("the market is in an uptrend")
    return Verdict(
        symbol=i.symbol,
        verdict=BUY,
        confidence=i.conviction_score,
        reasons=("; ".join(rules),),
        next_condition=(
            f"hold until a daily close below the 50-day low or the stop at {i.stop:.2f} "
            "— there is no profit target"
        ),
        explainer=explainer,
    )
