"""Convene the Investment Committee for a symbol and persist the minutes.

Assembles each member's facts from the layers that already exist — the
latest live scan (momentum), conviction batch, tracked-trade evaluation,
risk-heat headroom, portfolio-manager suggestions, market regime and the
options-eligibility verdict — then runs the pure
:func:`momentum.committee.convene` and appends the meeting to
``committee_meetings`` (append-only minutes).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.committee import CommitteeDecision, CommitteeInputs, convene
from momentum.persistence.models.committee_meeting import CommitteeMeeting
from momentum.persistence.repositories.committee import CommitteeMeetingRepository

_log = logging.getLogger(__name__)

# The risk-heat ceiling the platform's dynamic risk budget enforces (5%).
HEAT_CEILING_PCT = 0.05


def _scan_facts(session: Session, symbol: str) -> tuple[float | None, float | None, str | None]:
    """(momentum_score, conviction_score, conviction_band) from the newest data."""
    from momentum.api.services import resolve_active_run_id
    from momentum.persistence.models.conviction_score import ConvictionScore
    from momentum.persistence.models.scan_result import ScanResult

    momentum: float | None = None
    conviction: float | None = None
    band: str | None = None
    run_id = resolve_active_run_id(session)
    if run_id is not None:
        scan = session.scalars(
            select(ScanResult).where(ScanResult.run_id == run_id, ScanResult.symbol == symbol)
        ).first()
        if scan is not None and scan.momentum_score is not None:
            momentum = float(scan.momentum_score)
        conv = session.scalars(
            select(ConvictionScore).where(
                ConvictionScore.run_id == run_id, ConvictionScore.symbol == symbol
            )
        ).first()
        if conv is not None:
            conviction = float(conv.score)
            band = str(conv.band)
    return momentum, conviction, band


def _thesis_facts(session: Session, symbol: str) -> tuple[str | None, str | None, float | None]:
    from momentum.persistence.models.tracked_trade import TrackedTrade
    from momentum.persistence.models.trade_evaluation import TradeEvaluation

    trade = session.scalars(
        select(TrackedTrade).where(TrackedTrade.symbol == symbol, TrackedTrade.status == "open")
    ).first()
    if trade is None:
        return None, None, None
    latest = session.scalars(
        select(TradeEvaluation)
        .where(TradeEvaluation.trade_uid == trade.trade_uid)
        .order_by(TradeEvaluation.evaluated_at.desc())
        .limit(1)
    ).first()
    if latest is None:
        return None, None, None
    strength = float(latest.thesis_strength) if latest.thesis_strength is not None else None
    return str(latest.health), str(latest.action), strength


def _heat_headroom(session: Session) -> float | None:
    """Fraction of the 5% heat budget still free (from open journal trades)."""
    from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot
    from momentum.persistence.models.trade import Trade

    snapshot = session.scalars(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.as_of.desc()).limit(1)
    ).first()
    equity = float(snapshot.equity) if snapshot is not None and snapshot.equity else None
    if equity is None or equity <= 0:
        return None
    open_trades = session.scalars(select(Trade).where(Trade.status == "open")).all()
    at_risk = sum(float(t.initial_risk or 0.0) for t in open_trades)
    heat = at_risk / equity
    return max(1.0 - heat / HEAT_CEILING_PCT, 0.0)


def _regime_label(session: Session) -> str | None:
    from momentum.persistence.models.market_regime import MarketRegime

    row = session.scalars(select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)).first()
    return str(row.regime) if row is not None else None


def build_inputs(
    session: Session, symbol: str, *, context: str = "entry", ts: dt.datetime | None = None
) -> CommitteeInputs:
    sym = symbol.upper()
    momentum, conviction, band = _scan_facts(session, sym)
    health, action, strength = _thesis_facts(session, sym)
    return CommitteeInputs(
        symbol=sym,
        context=context,
        ts=ts,
        momentum_score=momentum,
        conviction_score=conviction,
        conviction_band=band,
        thesis_health=health,
        thesis_action=action,
        thesis_strength=strength,
        heat_headroom_pct=_heat_headroom(session),
        portfolio_suggestion=None,  # joined at the route level when available
        portfolio_reason=None,
        regime=_regime_label(session),
        options_verdict=None,  # advisory; wired when the eligibility engine ran
    )


def convene_and_persist(
    session: Session,
    symbol: str,
    *,
    context: str = "entry",
    run_id: str | None = None,
    ts: dt.datetime | None = None,
) -> CommitteeDecision:
    """Hold the meeting and append the minutes (caller commits)."""
    inputs = build_inputs(session, symbol, context=context, ts=ts)
    decision = convene(inputs)
    CommitteeMeetingRepository(session).add(
        CommitteeMeeting(
            meeting_uid=uuid.uuid4().hex[:24],
            run_id=run_id,
            ts=decision.ts,
            symbol=decision.symbol,
            context=decision.context,
            action=decision.action.value,
            confidence=decision.confidence,
            agreement=decision.agreement,
            votes=[v.to_dict() for v in decision.votes],
            consensus=decision.consensus[:2000],
            dissent=decision.dissent[:2000],
            narrative=decision.narrative[:3000],
        )
    )
    session.flush()
    return decision


def recent_meetings(
    session: Session, *, symbol: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    return [
        m.to_dict() for m in CommitteeMeetingRepository(session).recent(symbol=symbol, limit=limit)
    ]
