"""Read-only service layer for the API.

Keeps query logic out of the HTTP handlers and returns API schema objects, so
routes are trivial and fully typed. Every function takes an explicit ``Session``;
nothing here mutates state.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from momentum.analytics import attribution as attr
from momentum.analytics.performance import analyze_performance
from momentum.analytics.trade_analysis import TradeStats, compute_trade_stats
from momentum.api.schemas import (
    AnalogsOut,
    AttributionGroupOut,
    AttributionOut,
    AuditEventOut,
    CandidateDetailOut,
    ConfigFileOut,
    ConvictionScoreOut,
    DashboardOut,
    OpportunityOut,
    OptimizationResultOut,
    PerformanceOut,
    PortfolioSnapshotOut,
    RegimeOut,
    RiskBudgetOut,
    RiskMetricOut,
    RunDetailOut,
    RunOut,
    ScanResultOut,
    SignalOut,
    TradeOut,
)
from momentum.conviction.engine import ConvictionBand
from momentum.conviction.similar_setups import summarize
from momentum.opportunity.engine import OpportunityTier
from momentum.persistence.models import (
    ConvictionScore,
    MarketRegime,
    OpportunityClassification,
    OptimizationResult,
    PortfolioSnapshot,
    Run,
    RiskMetric,
    ScanResult,
    Signal,
    Trade,
)
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.conviction_scores import ConvictionScoreRepository
from momentum.persistence.repositories.opportunity_classifications import (
    OpportunityClassificationRepository,
)
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk import DynamicRiskBudgetEngine, RiskBudgetRequest


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


def list_snapshots(
    session: Session, *, run_id: str | None = None, limit: int = 1000
) -> list[PortfolioSnapshotOut]:
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


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Replace non-finite floats (inf/-inf/NaN) with None.

    Metrics like ``profit_factor`` are ``inf`` when there are no losing trades,
    and tail/skew stats can be ``NaN`` on tiny samples. Python's JSON encoder
    emits these as ``Infinity``/``NaN`` tokens, which strict ``JSON.parse`` (the
    browser) rejects — breaking the Analytics view. Map them to ``null`` so the
    payload is always valid JSON; the UI already renders ``None`` as "—".
    """
    return {
        k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in value.items()
    }


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
        performance = _json_safe(
            {
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
        )

    return PerformanceOut(
        run_id=run_id,
        n_trades=len(trades),
        trade_stats=_json_safe(asdict(stats)),
        performance=performance,
    )


def dashboard_summary(session: Session, *, run_id: str | None = None) -> DashboardOut:
    """One aggregate payload for the Dashboard view (regime, scans, trades, P&L)."""
    snap_stmt = select(PortfolioSnapshot)
    if run_id:
        snap_stmt = snap_stmt.where(PortfolioSnapshot.run_id == run_id)
    latest_snap = session.scalars(
        snap_stmt.order_by(PortfolioSnapshot.session_date.desc()).limit(1)
    ).first()

    open_stmt = select(func.count()).select_from(Trade).where(Trade.status == "open")
    if run_id:
        open_stmt = open_stmt.where(Trade.run_id == run_id)
    open_trades = int(session.scalar(open_stmt) or 0)

    return DashboardOut(
        latest_regime=latest_regime(session),
        latest_snapshot=(
            PortfolioSnapshotOut.model_validate(latest_snap) if latest_snap is not None else None
        ),
        top_scans=list_scans(session, run_id=run_id, passed_only=True, limit=8),
        recent_trades=list_trades(session, run_id=run_id, limit=8),
        open_trades=open_trades,
        performance=performance_summary(session, run_id=run_id),
    )


def list_config_files() -> list[str]:
    """Names of the available configuration templates (Settings view)."""
    config_dir = _config_dir()
    if not config_dir.is_dir():
        return []
    return sorted(p.name for p in config_dir.glob("*.yaml"))


def read_config_file(name: str) -> ConfigFileOut | None:
    """Read one configuration file by name (path-traversal safe)."""
    config_dir = _config_dir()
    target = (config_dir / name).resolve()
    if config_dir not in target.parents or not target.is_file():
        return None  # outside config/ or missing
    content = target.read_text()
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        parsed = None
    return ConfigFileOut(
        name=name, content=content, parsed=parsed if isinstance(parsed, dict) else None
    )


def _config_dir() -> Path:
    """Resolve the repository ``config/`` directory (overridable via env)."""
    override = os.environ.get("MRP_CONFIG_DIR")
    if override:
        return Path(override).resolve()
    # src/momentum/api/services.py -> repo root is three parents up from the package
    return (Path(__file__).resolve().parents[3] / "config").resolve()


# --------------------------------------------------------------------------- #
# Research workflow: runs, conviction, opportunity, analogs, candidate aggregate
# --------------------------------------------------------------------------- #
def list_runs(session: Session) -> list[RunOut]:
    """Distinct research runs seen across scans and trades (run selector)."""
    run_ids: set[str] = set()
    for col in (ScanResult.run_id, Trade.run_id):
        run_ids.update(r for (r,) in session.execute(select(col).distinct()) if r)
    return [RunOut(run_id=r) for r in sorted(run_ids)]


def list_recent_runs(
    session: Session, *, mode: str | None = None, limit: int = 20
) -> list[RunDetailOut]:
    """Recent persisted session runs with their lifecycle/result (Paper screen)."""
    stmt = select(Run)
    if mode:
        stmt = stmt.where(Run.mode == mode)
    stmt = stmt.order_by(Run.started_at.desc()).limit(limit)
    return [RunDetailOut.model_validate(row) for row in session.scalars(stmt)]


def list_audit(
    session: Session, *, run_id: str | None = None, limit: int = 100
) -> list[AuditEventOut]:
    """Recent audit events, newest first (optionally scoped to a run)."""
    repo = AuditLogRepository(session)
    events = repo.by_run(run_id)[-limit:][::-1] if run_id else list(repo.recent(limit))
    return [AuditEventOut.model_validate(e) for e in events]


def _humanize(name: str) -> str:
    """Turn a component key (``relative_volume``) into a phrase (``relative volume``)."""
    pretty = name.replace("_", " ").strip()
    # A few nicer aliases for the common factors.
    aliases = {
        "distance to ath": "proximity to all-time highs",
        "regime": "market regime",
        "historical edge": "historical analog performance",
        "sector strength": "sector leadership",
        "trend strength": "trend quality",
        "volatility penalty": "volatility",
    }
    return aliases.get(pretty, pretty)


def _conviction_narrative(out: ConvictionScoreOut) -> str | None:
    """Plain-language summary built from the breakdown's per-factor contributions."""
    breakdown = out.breakdown or {}
    components = breakdown.get("components")
    if not isinstance(components, list) or not components:
        return None
    comps = [
        c
        for c in components
        if isinstance(c, dict) and isinstance(c.get("contribution"), int | float)
    ]
    if not comps:
        return None
    comps.sort(key=lambda c: float(c["contribution"]), reverse=True)
    positives = [c for c in comps if float(c["contribution"]) > 0][:3]
    negatives = [c for c in comps if float(c["contribution"]) < 0]
    if not positives:
        return None
    drivers = [_humanize(str(c.get("name", ""))) for c in positives]
    if len(drivers) == 1:
        driver_text = drivers[0]
    elif len(drivers) == 2:
        driver_text = f"{drivers[0]} and {drivers[1]}"
    else:
        driver_text = f"{drivers[0]}, {drivers[1]} and {drivers[2]}"
    text = f"{out.symbol} scores {out.score:.0f} ({out.band}), driven by strong {driver_text}"
    if negatives:
        worst = min(negatives, key=lambda c: float(c["contribution"]))
        text += f", held back by {_humanize(str(worst.get('name', '')))}"
    return text + "."


def _with_narrative(out: ConvictionScoreOut) -> ConvictionScoreOut:
    return out.model_copy(update={"narrative": _conviction_narrative(out)})


def list_conviction(
    session: Session, *, symbol: str | None = None, run_id: str | None = None, limit: int = 100
) -> list[ConvictionScoreOut]:
    stmt = select(ConvictionScore)
    if symbol:
        stmt = stmt.where(ConvictionScore.symbol == symbol.upper())
    if run_id:
        stmt = stmt.where(ConvictionScore.run_id == run_id)
    stmt = stmt.order_by(ConvictionScore.as_of.desc()).limit(limit)
    return [
        _with_narrative(ConvictionScoreOut.model_validate(row)) for row in session.scalars(stmt)
    ]


def latest_conviction(
    session: Session, symbol: str, run_id: str | None = None
) -> ConvictionScoreOut | None:
    rows = ConvictionScoreRepository(session).for_symbol(symbol, run_id)
    return _with_narrative(ConvictionScoreOut.model_validate(rows[0])) if rows else None


def _attribution_group(key: str, stats: TradeStats) -> AttributionGroupOut:
    safe = _json_safe(asdict(stats))
    return AttributionGroupOut(
        key=key,
        num_trades=stats.num_trades,
        expectancy_r=safe["expectancy_r"],
        profit_factor=safe["profit_factor"],
        avg_winner_r=safe["avg_winner_r"],
        avg_loser_r=safe["avg_loser_r"],
        win_rate=safe["win_rate"],
        net_profit=safe["net_profit"],
    )


def performance_attribution(
    session: Session, *, run_id: str | None = None, min_trades: int = 1
) -> AttributionOut:
    """Slice closed-trade performance by sector, regime and exit reason."""
    trades = TradeRepository(session).analytics_trades(run_id)

    def groups(by: dict[str, TradeStats]) -> list[AttributionGroupOut]:
        return [_attribution_group(k, v) for k, v in by.items()]

    return AttributionOut(
        run_id=run_id,
        by_sector=groups(attr.by_sector(trades, min_trades=min_trades)),
        by_regime=groups(attr.by_regime(trades, min_trades=min_trades)),
        by_exit_reason=groups(attr.by_exit_reason(trades, min_trades=min_trades)),
    )


def list_opportunity(
    session: Session, *, symbol: str | None = None, run_id: str | None = None, limit: int = 100
) -> list[OpportunityOut]:
    stmt = select(OpportunityClassification)
    if symbol:
        stmt = stmt.where(OpportunityClassification.symbol == symbol.upper())
    if run_id:
        stmt = stmt.where(OpportunityClassification.run_id == run_id)
    stmt = stmt.order_by(OpportunityClassification.as_of.desc()).limit(limit)
    return [OpportunityOut.model_validate(row) for row in session.scalars(stmt)]


def latest_opportunity(
    session: Session, symbol: str, run_id: str | None = None
) -> OpportunityOut | None:
    rows = OpportunityClassificationRepository(session).for_symbol(symbol, run_id)
    return OpportunityOut.model_validate(rows[0]) if rows else None


def _latest_scan(session: Session, symbol: str, run_id: str | None = None) -> ScanResultOut | None:
    stmt = select(ScanResult).where(ScanResult.symbol == symbol.upper())
    if run_id:
        stmt = stmt.where(ScanResult.run_id == run_id)
    row = session.scalars(stmt.order_by(ScanResult.as_of.desc()).limit(1)).first()
    return ScanResultOut.model_validate(row) if row is not None else None


def analogs(
    session: Session,
    *,
    symbol: str | None = None,
    regime: str | None = None,
    sector: str | None = None,
    run_id: str | None = None,
    limit: int = 50,
) -> AnalogsOut:
    """Closed trades from setups like this one (same regime + sector cohort)."""
    sym = symbol.upper() if symbol else None
    if sym and sector is None:
        scan = _latest_scan(session, sym, run_id)
        sector = scan.sector if scan is not None else None
    if regime is None:
        reg = latest_regime(session)
        regime = reg.regime if reg is not None else None

    matched = [
        t
        for t in TradeRepository(session).closed(run_id)
        if t.r_multiple is not None
        and (regime is None or t.regime_label == regime)
        and (sector is None or t.sector == sector)
    ]
    stats = summarize(matched)
    recent = sorted(matched, key=lambda t: t.exit_ts or t.entry_ts, reverse=True)[:limit]
    return AnalogsOut(
        symbol=sym,
        regime=regime,
        sector=sector,
        sample_size=stats.sample_size,
        expectancy_r=stats.expectancy_r,
        win_rate=stats.win_rate,
        avg_winner_r=stats.avg_winner_r,
        avg_loser_r=stats.avg_loser_r,
        trades=[TradeOut.model_validate(t) for t in recent],
    )


def _candidate_risk_budget(
    session: Session,
    conviction: ConvictionScoreOut | None,
    opportunity: OpportunityOut | None,
    run_id: str | None,
) -> RiskBudgetOut | None:
    """Size a candidate's risk budget from its conviction band + opportunity tier."""
    if conviction is None:
        return None
    try:
        band = ConvictionBand(conviction.band)
    except ValueError:
        return None
    tier: OpportunityTier | None = None
    if opportunity is not None:
        try:
            tier = OpportunityTier(opportunity.tier)
        except ValueError:
            tier = None

    snap_stmt = select(PortfolioSnapshot)
    if run_id:
        snap_stmt = snap_stmt.where(PortfolioSnapshot.run_id == run_id)
    snap = session.scalars(
        snap_stmt.order_by(PortfolioSnapshot.session_date.desc()).limit(1)
    ).first()
    equity = snap.equity if snap is not None else 100_000.0
    heat = snap.portfolio_heat if snap is not None else 0.0

    b = DynamicRiskBudgetEngine().budget(
        RiskBudgetRequest(
            equity=equity,
            portfolio_heat_used=heat,
            conviction_band=band,
            opportunity_tier=tier,
            symbol=conviction.symbol,
        )
    )
    return RiskBudgetOut(
        conviction_band=b.conviction_band.value if b.conviction_band else None,
        opportunity_tier=b.opportunity_tier.value if b.opportunity_tier else None,
        home_run=b.home_run,
        base_pct=b.base_pct,
        requested_pct=b.requested_pct,
        granted_pct=b.granted_pct,
        risk_dollars=b.risk_dollars,
        binding_constraint=b.binding_constraint,
        portfolio_heat_used=b.portfolio_heat_used,
        portfolio_heat_after=b.portfolio_heat_after,
        reasons=list(b.reasons),
    )


def candidate_detail(
    session: Session, symbol: str, run_id: str | None = None
) -> CandidateDetailOut:
    """One aggregate that fills the Scan inspector (steps 2-4 at a glance)."""
    sym = symbol.upper()
    scan = _latest_scan(session, sym, run_id)
    conviction = latest_conviction(session, sym, run_id)
    opportunity = latest_opportunity(session, sym, run_id)
    sector = scan.sector if scan is not None else None
    setup_analogs = analogs(session, symbol=sym, sector=sector, run_id=run_id)
    risk_budget = _candidate_risk_budget(session, conviction, opportunity, run_id)
    return CandidateDetailOut(
        symbol=sym,
        scan=scan,
        conviction=conviction,
        opportunity=opportunity,
        analogs=setup_analogs,
        risk_budget=risk_budget,
    )
