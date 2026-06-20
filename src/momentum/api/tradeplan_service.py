"""Service layer for read-only trade-plan generation.

Assembles the engine inputs for a symbol from the scan (price/ATR/EMAs/ATH), the
latest conviction + regime, the historical-analog cohort and the candidate's risk
budget, then runs the pure :class:`TradePlanEngine`. It never places a trade.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.analytics.trade_analysis import compute_trade_stats
from momentum.api import services
from momentum.api.schemas import TradePlanOut
from momentum.persistence.models import PortfolioSnapshot, ScanResult
from momentum.persistence.repositories.trades import TradeRepository
from momentum.tradeplan import TradePlanEngine, TradePlanInputs


@dataclass(frozen=True, slots=True)
class _AnalogStats:
    sample_size: int
    expectancy_r: float | None
    win_rate: float | None
    avg_winner_r: float | None
    avg_loser_r: float | None
    avg_winner_holding_days: float | None
    avg_mfe_r: float | None


def _analog_stats(
    session: Session, *, sector: str | None, regime: str | None, run_id: str | None
) -> _AnalogStats:
    """Stats for closed trades in the same regime + sector cohort."""
    cohort = [
        t
        for t in TradeRepository(session).analytics_trades(run_id)
        if (regime is None or t.regime == regime) and (sector is None or t.sector == sector)
    ]
    if not cohort:
        return _AnalogStats(0, None, None, None, None, None, None)
    stats = compute_trade_stats(cohort)
    winner_mfes = [t.mfe_r for t in cohort if t.is_winner and t.mfe_r is not None]
    avg_mfe = sum(winner_mfes) / len(winner_mfes) if winner_mfes else None
    return _AnalogStats(
        sample_size=stats.num_trades,
        expectancy_r=stats.expectancy_r,
        win_rate=stats.win_rate,
        avg_winner_r=stats.avg_winner_r,
        avg_loser_r=stats.avg_loser_r,
        avg_winner_holding_days=stats.avg_winner_holding_days,
        avg_mfe_r=avg_mfe,
    )


def _latest_equity(session: Session, run_id: str | None) -> float:
    stmt = select(PortfolioSnapshot)
    if run_id:
        stmt = stmt.where(PortfolioSnapshot.run_id == run_id)
    snap = session.scalars(stmt.order_by(PortfolioSnapshot.session_date.desc()).limit(1)).first()
    return snap.equity if snap is not None else 100_000.0


def trade_plan(session: Session, symbol: str, run_id: str | None = None) -> TradePlanOut | None:
    """Derive a trade plan for ``symbol`` (None if there is no scan price/ATR)."""
    sym = symbol.upper()
    stmt = select(ScanResult).where(ScanResult.symbol == sym)
    if run_id:
        stmt = stmt.where(ScanResult.run_id == run_id)
    scan = session.scalars(stmt.order_by(ScanResult.as_of.desc()).limit(1)).first()
    if scan is None or scan.price is None or scan.atr is None:
        return None

    conviction = services.latest_conviction(session, sym, run_id)
    opportunity = services.latest_opportunity(session, sym, run_id)
    regime = services.latest_regime(session)
    budget = services._candidate_risk_budget(session, conviction, opportunity, run_id)
    analogs = _analog_stats(
        session, sector=scan.sector, regime=regime.regime if regime else None, run_id=run_id
    )

    inputs = TradePlanInputs(
        symbol=sym,
        price=scan.price,
        atr=scan.atr,
        ema_fast=scan.ema_fast,
        ema_mid=scan.ema_mid,
        ema_slow=scan.ema_slow,
        distance_from_ath=scan.distance_from_ath,
        relative_volume=scan.relative_volume,
        sector=scan.sector,
        conviction_score=conviction.score if conviction else None,
        conviction_band=conviction.band if conviction else None,
        regime=regime.regime if regime else None,
        analog_sample_size=analogs.sample_size,
        analog_expectancy_r=analogs.expectancy_r,
        analog_win_rate=analogs.win_rate,
        analog_avg_winner_r=analogs.avg_winner_r,
        analog_avg_loser_r=analogs.avg_loser_r,
        analog_avg_winner_holding_days=analogs.avg_winner_holding_days,
        analog_avg_mfe_r=analogs.avg_mfe_r,
        risk_pct=budget.granted_pct if budget else None,
        risk_dollars=budget.risk_dollars if budget else None,
        equity=_latest_equity(session, run_id),
    )
    plan = TradePlanEngine().plan(inputs)
    return TradePlanOut(**plan.to_dict()) if plan is not None else None
