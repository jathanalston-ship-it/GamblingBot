"""The instrument-selection engine.

``InstrumentSelectionEngine.select(thesis, context)`` scores all four bullish
expressions, applies hard liquidity/availability gates, and returns the
best-fit :class:`InstrumentDecision` with a suggested structure and an auditable
rationale. It never sizes risk or routes orders — it only chooses *how* to
express a thesis.
"""

from __future__ import annotations

from collections.abc import Callable

from momentum.core.enums import InstrumentType
from momentum.instruments import scoring
from momentum.instruments.selection_config import InstrumentSelectionConfig
from momentum.instruments.structures import build_structure
from momentum.instruments.types import (
    CandidateScore,
    InstrumentContext,
    InstrumentDecision,
    TradeThesis,
)

_Scorer = Callable[
    [TradeThesis, InstrumentContext, InstrumentSelectionConfig], tuple[float, dict[str, float]]
]

_SCORERS: dict[InstrumentType, _Scorer] = {
    InstrumentType.SHARES: scoring.score_shares,
    InstrumentType.LONG_CALL: scoring.score_long_call,
    InstrumentType.VERTICAL_CALL_SPREAD: scoring.score_vertical_call_spread,
    InstrumentType.LEAPS: scoring.score_leaps,
}

# Tie-break preference: simpler / safer first.
_PRIORITY: dict[InstrumentType, int] = {
    InstrumentType.SHARES: 0,
    InstrumentType.VERTICAL_CALL_SPREAD: 1,
    InstrumentType.LONG_CALL: 2,
    InstrumentType.LEAPS: 3,
}


class InstrumentSelectionEngine:
    """Chooses shares / long call / vertical spread / LEAPS for a bullish thesis."""

    def __init__(self, config: InstrumentSelectionConfig | None = None) -> None:
        self.config = config or InstrumentSelectionConfig()

    def select(self, thesis: TradeThesis, context: InstrumentContext) -> InstrumentDecision:
        cfg = self.config
        candidates: list[CandidateScore] = []
        for instrument, scorer in _SCORERS.items():
            score, components = scorer(thesis, context, cfg)
            eligible, reasons = self._eligibility(instrument, context)
            candidates.append(
                CandidateScore(
                    instrument=instrument,
                    score=score,
                    eligible=eligible,
                    components=components,
                    reasons=reasons,
                )
            )

        eligible_candidates = [c for c in candidates if c.eligible]
        pool = eligible_candidates or [
            c for c in candidates if c.instrument is InstrumentType.SHARES
        ]
        # rank by score, tie-break by the safety priority (lower first)
        ranked = sorted(pool, key=lambda c: (-c.score, _PRIORITY[c.instrument]))
        winner = ranked[0]
        margin = winner.score - ranked[1].score if len(ranked) > 1 else winner.score

        structure = build_structure(winner.instrument, thesis, context, cfg)
        rationale = self._rationale(winner, ranked, context, margin)

        return InstrumentDecision(
            symbol=thesis.symbol.upper(),
            instrument=winner.instrument,
            structure=structure,
            confidence=round(winner.score, 4),
            margin=round(margin, 4),
            candidates=tuple(candidates),
            rationale=rationale,
            iv_rv_ratio=context.iv_rv_ratio,
            signal_id=thesis.signal_id,
        )

    # -- gates -------------------------------------------------------------- #
    def _eligibility(
        self, instrument: InstrumentType, ctx: InstrumentContext
    ) -> tuple[bool, tuple[str, ...]]:
        gates = self.config.liquidity
        reasons: list[str] = []
        if instrument is InstrumentType.SHARES:
            if ctx.share_dollar_volume < gates.min_share_dollar_volume:
                reasons.append("underlying below the liquidity floor")
            return (not reasons, tuple(reasons))

        # option instruments
        if not ctx.has_options:
            reasons.append("no listed options")
        if ctx.options_open_interest < gates.min_option_open_interest:
            reasons.append("option open interest below floor")
        if ctx.options_spread_pct > gates.max_option_spread_pct:
            reasons.append("option spread too wide")
        if instrument is InstrumentType.LEAPS and not ctx.leaps_available:
            reasons.append("no liquid long-dated (LEAPS) expiries")
        return (not reasons, tuple(reasons))

    # -- explanation -------------------------------------------------------- #
    def _rationale(
        self,
        winner: CandidateScore,
        ranked: list[CandidateScore],
        ctx: InstrumentContext,
        margin: float,
    ) -> tuple[str, ...]:
        out = [f"Chose {winner.instrument.display} (score {winner.score:.2f})."]
        top = sorted(winner.components.items(), key=lambda kv: kv[1], reverse=True)[:2]
        if top:
            drivers = ", ".join(f"{name} {val:.2f}" for name, val in top)
            out.append(f"Primary drivers: {drivers}.")
        out.append(
            f"Options richness IV/RV = {ctx.iv_rv_ratio:.2f} "
            f"({'rich' if ctx.iv_rv_ratio >= self.config.iv_rich else 'cheap' if ctx.iv_rv_ratio <= self.config.iv_cheap else 'neutral'})."
        )
        if len(ranked) > 1:
            out.append(f"Runner-up: {ranked[1].instrument.display} (margin {margin:.2f}).")
        if margin < self.config.min_margin:
            out.append("Low decisiveness — margin under threshold; treat as a close call.")
        ineligible = [c for c in (winner,) if not c.eligible]
        if ineligible:
            out.append("Note: chosen as the shares fallback (no eligible option structure).")
        return tuple(out)
