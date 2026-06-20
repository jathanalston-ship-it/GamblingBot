"""The Market Command Center: one read-only aggregate for the landing page.

Pulls together the regime, the multi-horizon opportunities, the standout setups,
portfolio heat, recent performance, watchlist changes and freshly-triggered
setups by reusing the existing service layer — it owns no new persistence.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import lifecycle_service, services, watchlist_service
from momentum.api.schemas import (
    CommandCenterOut,
    CommandPerformanceOut,
    ConvictionScoreOut,
    SectorHighlightOut,
    WatchlistComparisonOut,
    WatchlistEntryOut,
)
from momentum.persistence.models import ConvictionScore, PortfolioSnapshot

_TOP_N = 5


def command_center(session: Session, *, run_id: str | None = None) -> CommandCenterOut:
    regime = services.latest_regime(session)

    # Multi-horizon opportunities (top 5 each) + the best reward:risk across them.
    watchlists = watchlist_service.get_watchlists(session, run_id=run_id)
    by_h = {h.horizon: h.entries for h in watchlists.horizons}
    daily = by_h.get("daily", [])[:_TOP_N]
    weekly = by_h.get("weekly", [])[:_TOP_N]
    monthly = by_h.get("monthly", [])[:_TOP_N]
    all_entries = [e for h in watchlists.horizons for e in h.entries]
    best_rr: WatchlistEntryOut | None = max(
        (e for e in all_entries if e.reward_risk is not None),
        key=lambda e: e.reward_risk or 0.0,
        default=None,
    )

    # Highest-conviction setup.
    hc_stmt = select(ConvictionScore).order_by(ConvictionScore.score.desc()).limit(1)
    if run_id is not None:
        hc_stmt = hc_stmt.where(ConvictionScore.run_id == run_id)
    hc_row = session.scalars(hc_stmt).first()
    highest_conviction = ConvictionScoreOut.model_validate(hc_row) if hc_row is not None else None

    # Most attractive sector (highest average conviction across current candidates).
    candidates, _ = watchlist_service._load_candidates(session, run_id)
    sector_scores: dict[str, list[float]] = {}
    for cand in candidates:
        if cand.sector:
            sector_scores.setdefault(cand.sector, []).append(cand.base_conviction)
    top_sector: SectorHighlightOut | None = None
    if sector_scores:
        # Prefer sectors with breadth (>= 2 names) so a single hot stock doesn't win.
        pool = {s: v for s, v in sector_scores.items() if len(v) >= 2} or sector_scores
        sector, scores = max(pool.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        top_sector = SectorHighlightOut(
            sector=sector, avg_conviction=round(sum(scores) / len(scores), 1), count=len(scores)
        )

    # Portfolio heat / equity / daily P&L from the latest snapshot.
    snap_stmt = select(PortfolioSnapshot)
    if run_id is not None:
        snap_stmt = snap_stmt.where(PortfolioSnapshot.run_id == run_id)
    snap = session.scalars(
        snap_stmt.order_by(PortfolioSnapshot.session_date.desc()).limit(1)
    ).first()
    portfolio_heat = snap.portfolio_heat if snap is not None else None
    equity = snap.equity if snap is not None else None
    daily_pnl = None
    if snap is not None:
        daily_pnl = snap.daily_pnl
        if daily_pnl is None and snap.daily_return is not None:
            daily_pnl = snap.equity * snap.daily_return

    # Recent performance headline.
    perf = services.performance_summary(session, run_id=run_id)
    ts = perf.trade_stats
    performance = CommandPerformanceOut(
        n_trades=perf.n_trades,
        expectancy_r=ts.get("expectancy_r"),
        profit_factor=ts.get("profit_factor"),
        win_rate=ts.get("win_rate"),
        net_pnl=ts.get("net_profit"),
    )

    # Watchlist changes — diff the two most recent daily generations.
    dates = watchlist_service.watchlist_dates(session, run_id=run_id, limit=2)
    changes: WatchlistComparisonOut | None = None
    if len(dates) >= 2:
        changes = watchlist_service.compare_watchlists(
            session, horizon="daily", base=dates[1], against=dates[0], run_id=run_id
        )

    # Recently-triggered setups.
    recent_triggered = lifecycle_service.list_lifecycles(session, run_id=run_id, state="Triggered")[
        :8
    ]

    as_of = watchlists.as_of or (regime.as_of if regime is not None else None)
    return CommandCenterOut(
        run_id=run_id,
        as_of=as_of,
        regime=regime,
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        highest_conviction=highest_conviction,
        best_reward_risk=best_rr,
        top_sector=top_sector,
        portfolio_heat=portfolio_heat,
        equity=equity,
        daily_pnl=daily_pnl,
        performance=performance,
        watchlist_changes=changes,
        recent_triggered=recent_triggered,
    )
