"""The daily paper pipeline: scan -> conviction -> risk -> paper order -> journal.

:class:`DailyPaperPipeline` wires the finished engines into one vertical slice.
For each ranked scan candidate it: scores conviction, gates on a minimum band,
turns the conviction band into a per-trade risk budget, sizes/stops/vets the
trade through the risk gateway, routes an approved order to the paper broker,
applies the fill to the portfolio, and journals the open trade. Every candidate
yields a :class:`TradeDecision`, so a run is fully explainable.

The pipeline owns no policy of its own — thresholds live in the injected engines
and configs. It is deterministic: the same scan, regime and seeded configs
produce the same decisions, and re-running with the same ``run_id`` is
idempotent (the journal de-duplicates open trades).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from momentum.conviction.engine import ConvictionBand, ConvictionEngine, ConvictionResult
from momentum.conviction.inputs import ConvictionInputs
from momentum.core.enums import RegimeState, Side
from momentum.execution.broker import Broker, OrderRequest
from momentum.portfolio.journal import TradeJournal
from momentum.portfolio.portfolio import Portfolio
from momentum.risk.risk_budget import DynamicRiskBudgetEngine, RiskBudgetRequest
from momentum.risk.risk_manager import RiskManager
from momentum.risk.types import TradeProposal
from momentum.universe.screener import ScanCandidate, ScanResult

# Conviction bands in ascending strength, for "at least this band" gating.
_BAND_ORDER: tuple[ConvictionBand, ...] = (
    ConvictionBand.LOW,
    ConvictionBand.MEDIUM,
    ConvictionBand.HIGH,
    ConvictionBand.EXTREME,
)

# RegimeState label -> the conviction engine's regime_map key.
_REGIME_TO_CONVICTION: dict[RegimeState, str] = {
    RegimeState.BULLISH: "bull",
    RegimeState.NEUTRAL: "neutral",
    RegimeState.BEARISH: "bear",
}


@dataclass(frozen=True, slots=True)
class TradeDecision:
    """The outcome of running one candidate through the pipeline."""

    symbol: str
    # opened | already_open | no_atr | rejected_conviction | rejected_budget | vetoed | not_filled
    outcome: str
    conviction_score: float | None = None
    conviction_band: str | None = None
    approved_shares: int | None = None
    entry_price: float | None = None
    reason: str | None = None
    trade_id: int | None = None

    @property
    def opened(self) -> bool:
        return self.outcome == "opened"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "outcome": self.outcome,
            "conviction_score": self.conviction_score,
            "conviction_band": self.conviction_band,
            "approved_shares": self.approved_shares,
            "entry_price": self.entry_price,
            "reason": self.reason,
            "trade_id": self.trade_id,
        }


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """Aggregate result of one pipeline run."""

    run_id: str | None
    as_of: dt.date
    decisions: tuple[TradeDecision, ...]

    @property
    def considered(self) -> int:
        return len(self.decisions)

    @property
    def opened(self) -> tuple[TradeDecision, ...]:
        return tuple(d for d in self.decisions if d.opened)

    @property
    def num_opened(self) -> int:
        return len(self.opened)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "as_of": self.as_of.isoformat(),
            "considered": self.considered,
            "num_opened": self.num_opened,
            "decisions": [d.to_dict() for d in self.decisions],
        }


class DailyPaperPipeline:
    """Runs the scan -> conviction -> risk -> paper order -> journal slice."""

    def __init__(
        self,
        *,
        conviction: ConvictionEngine,
        risk: RiskManager,
        broker: Broker,
        portfolio: Portfolio,
        journal: TradeJournal,
        risk_budget: DynamicRiskBudgetEngine | None = None,
        min_conviction_band: ConvictionBand = ConvictionBand.MEDIUM,
        entry_reason: str = "momentum_breakout",
    ) -> None:
        self.conviction = conviction
        self.risk = risk
        self.broker = broker
        self.portfolio = portfolio
        self.journal = journal
        self.risk_budget = risk_budget or DynamicRiskBudgetEngine()
        self.min_conviction_band = min_conviction_band
        self.entry_reason = entry_reason

    def run(
        self,
        scan: ScanResult,
        *,
        run_id: str | None = None,
        regime: RegimeState | None = None,
        ts: dt.datetime | None = None,
    ) -> PipelineReport:
        """Process every ranked candidate and return the per-candidate decisions."""
        when = ts or _as_datetime(scan.as_of)
        decisions = [
            self._process(candidate, run_id=run_id, regime=regime, ts=when)
            for candidate in scan.candidates
        ]
        return PipelineReport(run_id=run_id, as_of=when.date(), decisions=tuple(decisions))

    # -- one candidate ------------------------------------------------------ #
    def _process(
        self,
        candidate: ScanCandidate,
        *,
        run_id: str | None,
        regime: RegimeState | None,
        ts: dt.datetime,
    ) -> TradeDecision:
        symbol = candidate.symbol
        if symbol in self.portfolio.positions:
            return TradeDecision(symbol=symbol, outcome="already_open", reason="position held")
        if candidate.atr is None or candidate.atr <= 0:
            return TradeDecision(symbol=symbol, outcome="no_atr", reason="missing ATR")

        conv = self._score(candidate, regime)
        decision = TradeDecision(
            symbol=symbol,
            outcome="opened",
            conviction_score=round(conv.score, 4),
            conviction_band=conv.band.value,
        )
        if not self._meets_min_band(conv.band):
            return _with(decision, outcome="rejected_conviction", reason=f"band {conv.band.value}")

        account = self.portfolio.to_account_state(regime=regime)
        budget = self.risk_budget.budget(
            RiskBudgetRequest.from_account(account, conviction_band=conv.band, symbol=symbol)
        )
        if not budget.is_fundable:
            return _with(decision, outcome="rejected_budget", reason="no risk headroom")

        proposal = TradeProposal(
            symbol=symbol,
            entry_ref=candidate.price,
            atr=candidate.atr,
            side=Side.LONG,
            sector=candidate.sector,
        )
        assessment = self.risk.evaluate(
            proposal, account, run_id=run_id, risk_per_trade_pct=budget.granted_pct
        )
        if not assessment.approved:
            return _with(
                decision,
                outcome="vetoed",
                reason=assessment.binding_constraint or assessment.verdict.value,
            )

        order = self.broker.submit(
            OrderRequest(
                client_order_id=_order_id(run_id, symbol),
                symbol=symbol,
                side=Side.LONG,
                quantity=assessment.approved_shares,
                reference_price=candidate.price,
                ts=ts,
            )
        )
        if not order.is_filled:
            return _with(decision, outcome="not_filled", reason=order.reject_reason or "unfilled")

        fill = order.fills[-1]
        self.portfolio.on_fill(fill, sector=candidate.sector)
        self.portfolio.set_stop(symbol, assessment.initial_stop)
        trade = self.journal.open_trade(
            entry_fill=fill,
            assessment=assessment,
            run_id=run_id,
            sector=candidate.sector,
            regime_label=regime.value if regime else None,
            entry_reason=self.entry_reason,
            entry_volume=candidate.volume,
            entry_relative_volume=candidate.relative_volume,
        )
        return _with(
            decision,
            outcome="opened",
            approved_shares=order.filled_quantity,
            entry_price=order.avg_fill_price,
            trade_id=trade.id,
        )

    def _score(self, candidate: ScanCandidate, regime: RegimeState | None) -> ConvictionResult:
        inputs = ConvictionInputs(
            market_regime=_REGIME_TO_CONVICTION.get(regime) if regime else None,
            sector_strength=candidate.sector_rs,
            relative_volume=candidate.relative_volume,
            distance_to_ath=abs(candidate.distance_from_ath),
            momentum_score=candidate.momentum_score / 100.0,  # scanner score is 0..100
        )
        return self.conviction.score(inputs)

    def _meets_min_band(self, band: ConvictionBand) -> bool:
        return _BAND_ORDER.index(band) >= _BAND_ORDER.index(self.min_conviction_band)


def _with(decision: TradeDecision, **changes: Any) -> TradeDecision:
    from dataclasses import replace

    return replace(decision, **changes)


def _order_id(run_id: str | None, symbol: str) -> str:
    return f"{run_id or 'run'}:{symbol}"


def _as_datetime(as_of: Any) -> dt.datetime:
    """Coerce a scan ``as_of`` (pandas Timestamp / date / datetime) to UTC datetime."""
    to_pydatetime = getattr(as_of, "to_pydatetime", None)
    value = to_pydatetime() if callable(to_pydatetime) else as_of
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min, tzinfo=dt.UTC)
    raise TypeError(f"cannot coerce {as_of!r} to a datetime")
