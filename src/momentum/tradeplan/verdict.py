"""Trade-plan verdict — BUY / WATCH / WAIT / AVOID, always with the framework.

Pure: the service layer gathers live evidence (scan row, conviction now
and previous, regime, the trade plan, freshness, liquidity, earnings,
instrument eligibility) into :class:`VerdictInputs`; this module grades it
against explicit thresholds and returns a verdict that **never simply says
no** — every WAIT names exactly what to wait for, every AVOID names why
AND the next highest-probability condition that would change the thesis,
and every recommendation carries the full decision explainer (why this
trade / why now / why not yesterday / invalidation / improve / reduce /
why this stop / target / size / instrument).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BUY = "BUY"
WATCH = "WATCH"
WAIT = "WAIT"
AVOID = "AVOID"

# Explicit, explainable thresholds (mirroring the platform's other engines).
MIN_DOLLAR_VOLUME = 5_000_000.0  # below this, fills are fantasy
MIN_REWARD_RISK = 1.5  # anything under is structurally poor
GOOD_REWARD_RISK = 2.0
BUY_CONVICTION = 70.0  # the HIGH band
WATCH_CONVICTION = 55.0
AVOID_CONVICTION = 40.0
EXTENDED_ATR = 1.0  # price this many ATRs past ideal entry = chasing
MIN_RELATIVE_VOLUME = 0.8


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
            f"relative volume expanding above {max(i.relative_volume or 0, 1.5):.1f}x",
            "conviction moving further into the HIGH/EXTREME band",
            "the market regime strengthening toward bullish",
        ],
        "what_would_reduce_conviction": list(i.weak_factors)
        + (["a bearish regime flip"] if i.regime != "bearish" else []),
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


def evaluate_verdict(i: VerdictInputs) -> Verdict:  # noqa: PLR0912 — an explicit rule ladder
    reasons: list[str] = []
    explainer = _explainer(i)

    # ---- AVOID: structural problems no timing fixes -------------------------
    avoid: list[str] = []
    next_condition = ""
    if i.dollar_volume is not None and i.dollar_volume < MIN_DOLLAR_VOLUME:
        avoid.append(
            f"poor liquidity: ${i.dollar_volume / 1e6:.1f}M average dollar volume "
            f"(needs ${MIN_DOLLAR_VOLUME / 1e6:.0f}M+) — exits would move the price"
        )
        next_condition = (
            f"sustained dollar volume above ${MIN_DOLLAR_VOLUME / 1e6:.0f}M/day would "
            "make the setup tradeable"
        )
    if i.conviction_score is not None and i.conviction_score < AVOID_CONVICTION:
        avoid.append(
            f"low conviction ({i.conviction_score:.0f}/100): "
            + (", ".join(i.weak_factors) or "multiple weak components")
        )
        next_condition = next_condition or (
            f"conviction recovering above {WATCH_CONVICTION:.0f} — most likely via "
            + (i.weak_factors[0] if i.weak_factors else "momentum re-accelerating")
        )
    if i.reward_risk is not None and i.reward_risk < MIN_REWARD_RISK:
        avoid.append(
            f"bad risk/reward: {i.reward_risk:.1f}R to the final target "
            f"(needs {MIN_REWARD_RISK:.1f}R+)"
        )
        next_condition = next_condition or (
            "a pullback toward the stop level would restore the reward/risk — "
            f"an entry near {i.stop:.2f} changes the math"
            if i.stop
            else "a deeper entry would restore the reward/risk"
        )
    if i.momentum_score is not None and i.momentum_score < 20:
        avoid.append(f"weak trend: momentum score {i.momentum_score:.0f}/100")
        next_condition = next_condition or (
            "a reclaim of the rising 20/50EMA structure with expanding volume"
        )
    if avoid:
        return Verdict(
            symbol=i.symbol,
            verdict=AVOID,
            confidence=i.conviction_score,
            reasons=tuple(avoid),
            next_condition=next_condition,
            explainer=explainer,
        )

    # ---- WAIT: right idea, wrong moment -------------------------------------
    wait: list[str] = []
    if i.data_stale:
        wait.append("market data is stale — wait for a fresh scan before pricing an entry")
        next_condition = "the next completed scan with fresh bars"
    if (
        i.days_to_earnings is not None
        and i.earnings_block_days > 0
        and 0 <= i.days_to_earnings <= i.earnings_block_days
    ):
        wait.append(f"earnings in {i.days_to_earnings} day(s) — binary risk; wait for the report")
        next_condition = next_condition or "the earnings report clearing the binary risk"
    if i.regime == "bearish":
        wait.append("market regime is bearish — wait for market confirmation")
        next_condition = next_condition or (
            "the regime engine turning neutral/bullish (breadth + benchmark trend recovering)"
        )
    if (
        i.price is not None
        and i.entry is not None
        and i.atr is not None
        and i.atr > 0
        and i.price > i.entry + EXTENDED_ATR * i.atr
    ):
        wait.append(
            f"extended: price {i.price:.2f} is more than {EXTENDED_ATR:.0f} ATR above the "
            f"ideal entry {i.entry:.2f} — wait for a pullback toward {i.entry:.2f}"
        )
        next_condition = next_condition or f"a pullback into the entry zone near {i.entry:.2f}"
    if i.relative_volume is not None and i.relative_volume < MIN_RELATIVE_VOLUME:
        wait.append(
            f"volume is quiet ({i.relative_volume:.1f}x average) — wait for volume "
            "to confirm the move"
        )
        next_condition = next_condition or "relative volume expanding above 1.0x on an up day"
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
    score = i.conviction_score if i.conviction_score is not None else 0.0
    rr_ok = i.reward_risk is None or i.reward_risk >= GOOD_REWARD_RISK
    if score >= BUY_CONVICTION and rr_ok and i.entry is not None and i.stop is not None:
        reasons.append(
            f"conviction {score:.0f}/100 ({i.conviction_band or 'HIGH'}), "
            + (f"{i.reward_risk:.1f}R plan, " if i.reward_risk else "")
            + f"regime {i.regime or 'n/a'} — the framework's entry conditions are met"
        )
        return Verdict(
            symbol=i.symbol,
            verdict=BUY,
            confidence=score,
            reasons=tuple(reasons),
            next_condition="manage to plan: stop first, targets after",
            explainer=explainer,
        )

    if score >= WATCH_CONVICTION:
        reasons.append(
            f"conviction {score:.0f}/100 is building but below the {BUY_CONVICTION:.0f} entry bar"
        )
    else:
        reasons.append(f"conviction {score:.0f}/100 — the setup is early")
    if not rr_ok and i.reward_risk is not None:
        reasons.append(f"reward/risk {i.reward_risk:.1f}R is under the {GOOD_REWARD_RISK:.1f}R bar")
    if i.entry is None or i.stop is None:
        reasons.append("no complete trade plan yet — run a scan that surfaces it")
    trigger = (
        f"a close above {i.entry:.2f} with 1.5x volume would trigger the entry"
        if i.entry is not None
        else f"conviction crossing {BUY_CONVICTION:.0f} would trigger a plan"
    )
    return Verdict(
        symbol=i.symbol,
        verdict=WATCH,
        confidence=score,
        reasons=tuple(reasons),
        next_condition=trigger,
        explainer=explainer,
    )
