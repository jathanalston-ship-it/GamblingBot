"""Read-only service layer for the API.

Keeps query logic out of the HTTP handlers and returns API schema objects, so
routes are trivial and fully typed. Every function takes an explicit ``Session``;
nothing here mutates state.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.analytics.performance import analyze_performance
from momentum.analytics.trade_analysis import compute_trade_stats
from momentum.api.schemas import (
    OptimizationResultOut,
    PerformanceOut,
    PortfolioSnapshotOut,
    RegimeOut,
    RiskMetricOut,
    ScanResultOut,
    SignalOut,
    TradeOut,
)
from momentum.persistence.models import (
    MarketRegime,
    OptimizationResult,
    PortfolioSnapshot,
    RiskMetric,
    ScanResult,
    Signal,
    Trade,
)
from momentum.persistence.repositories.trades import TradeRepository


def list_signals(
    session: Session, *, symbol: str | None = None, run_id: str | None = None, limit: int = 100
) -> list[SignalOut]:
    stmt = select(Signal)
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol.upper())
    if run_id:
        stmt = stmt.where(Signal.run_id == run_id)
    stmt = stmt.order_by(Signal.ts.desc()).limit(limit)
    return [SignalOut.model_validate(row) for row in session.scalars(stmt)]


def list_trades(
    session: Session,
    *,
    symbol: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> list[TradeOut]:
    stmt = select(Trade)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol.upper())
    if status:
        stmt = stmt.where(Trade.status == status)
    if run_id:
        stmt = stmt.where(Trade.run_id == run_id)
    stmt = stmt.order_by(Trade.entry_ts.desc()).limit(limit)
    return [TradeOut.model_validate(row) for row in session.scalars(stmt)]


def list_regimes(session: Session, *, limit: int = 100) -> list[RegimeOut]:
    stmt = select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(limit)
    return [RegimeOut.model_validate(row) for row in session.scalars(stmt)]


def latest_regime(session: Session) -> RegimeOut | None:
    stmt = select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)
    row = session.scalars(stmt).first()
    return RegimeOut.model_validate(row) if row is not None else None


def list_snapshots(session: Session, *, run_id: str | None = None, limit: int = 1000) -> list[PortfolioSnapshotOut]:
    stmt = select(PortfolioSnapshot)
    if run_id:
        stmt = stmt.where(PortfolioSnapshot.run_id == run_id)
    stmt = stmt.order_by(PortfolioSnapshot.session_date.asc()).limit(limit)
    return [PortfolioSnapshotOut.model_validate(row) for row in session.scalars(stmt)]


def list_risk_metrics(
    session: Session,
    *,
    scope: str | None = None,
    window: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> list[RiskMetricOut]:
    stmt = select(RiskMetric)
    if scope:
        stmt = stmt.where(RiskMetric.scope == scope)
    if window:
        stmt = stmt.where(RiskMetric.window == window)
    if run_id:
        stmt = stmt.where(RiskMetric.run_id == run_id)
    stmt = stmt.order_by(RiskMetric.as_of.desc()).limit(limit)
    return [RiskMetricOut.model_validate(row) for row in session.scalars(stmt)]


def list_scans(
    session: Session, *, run_id: str | None = None, passed_only: bool = False, limit: int = 100
) -> list[ScanResultOut]:
    stmt = select(ScanResult)
    if run_id:
        stmt = stmt.where(ScanResult.run_id == run_id)
    if passed_only:
        stmt = stmt.where(ScanResult.passed.is_(True))
    stmt = stmt.order_by(ScanResult.as_of.desc(), ScanResult.rank.asc()).limit(limit)
    return [ScanResultOut.model_validate(row) for row in session.scalars(stmt)]


def list_optimizations(
    session: Session, *, study_name: str | None = None, limit: int = 100
) -> list[OptimizationResultOut]:
    stmt = select(OptimizationResult)
    if study_name:
        stmt = stmt.where(OptimizationResult.study_name == study_name)
    stmt = stmt.order_by(OptimizationResult.objective_value.desc()).limit(limit)
    return [OptimizationResultOut.model_validate(row) for row in session.scalars(stmt)]


def performance_summary(session: Session, *, run_id: str | None = None) -> PerformanceOut:
    """Trade stats (always) plus full performance metrics when an equity curve exists."""
    trades = TradeRepository(session).analytics_trades(run_id)
    stats = compute_trade_stats(trades)

    snap_stmt = select(PortfolioSnapshot)
    if run_id:
        snap_stmt = snap_stmt.where(PortfolioSnapshot.run_id == run_id)
    snapshots = list(session.scalars(snap_stmt.order_by(PortfolioSnapshot.session_date.asc())))

    performance: dict[str, Any] | None = None
    if len(snapshots) >= 2:
        equity = pd.Series(
            [s.equity for s in snapshots],
            index=pd.to_datetime([s.session_date for s in snapshots]),
        )
        report = analyze_performance(equity, trades)
        performance = {
            "total_return": report.total_return,
            "cagr": report.cagr,
            "annual_volatility": report.annual_volatility,
            "sharpe": report.sharpe,
            "sortino": report.sortino,
            "calmar": report.calmar,
            "max_drawdown": report.max_drawdown,
            "return_tail_ratio": report.return_tail_ratio,
            "objective": report.objective,
        }

    return PerformanceOut(
        run_id=run_id,
        n_trades=len(trades),
        trade_stats=asdict(stats),
        performance=performance,
    )
