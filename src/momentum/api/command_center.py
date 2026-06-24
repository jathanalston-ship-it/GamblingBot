"""The Market Command Center: one read-only aggregate for the landing page.

Pulls together the regime, the multi-horizon opportunities, the standout setups,
portfolio heat, recent performance, watchlist changes and freshly-triggered
setups by reusing the existing service layer — it owns no new persistence.

Resilience contract: this is the default landing page, so it must **never** 500
because data is missing or a schema/sub-service gap exists. Every independent
section is computed behind :func:`_safe`, which logs and falls back to an empty
value (rolling the session back so one failed query can't cascade). A fresh /
empty / partially-migrated / live database all yield a valid response — at worst
a fully empty-state one.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import lifecycle_service, services, watchlist_service
from momentum.api.schemas import (
    CommandCenterOut,
    CommandPerformanceOut,
    ConvictionScoreOut,
    LifecycleOut,
    RegimeOut,
    SectorHighlightOut,
    WatchlistComparisonOut,
    WatchlistEntryOut,
)
from momentum.persistence.models import ConvictionScore, PortfolioSnapshot, Run

_log = logging.getLogger("momentum.api.command_center")
_TOP_N = 5

T = TypeVar("T")


def _safe(session: Session, label: str, fn: Callable[[], T], default: T) -> T:
    """Run one aggregation section; on ANY failure log it and return *default*.

    Read-only landing-page sections are independent, so a single broken one (a
    missing column on an upgraded DB, a missing table, a bad sub-service) must
    degrade to empty rather than 500 the whole page. The session is rolled back so
    a failed query doesn't poison the connection for the remaining sections.
    """
    try:
        return fn()
    except Exception:  # noqa: BLE001 — landing page must never 500 on missing data
        _log.warning(
            "command_center: section %r failed; using empty fallback", label, exc_info=True
        )
        try:
            session.rollback()
        except Exception:  # noqa: BLE001 — best-effort recovery
            _log.debug("command_center: rollback after %r failed", label, exc_info=True)
        return default


def _finite(value: float | None) -> float | None:
    """Map a non-finite float (inf/-inf/NaN) to ``None`` (valid-JSON guarantee)."""
    if value is None:
        return None
    return value if math.isfinite(value) else None


def _effective_run_id(session: Session, run_id: str | None) -> str | None:
    """Resolve the run to display, falling back to *latest* for a missing run.

    The frontend auto-selects a run id (e.g. ``demo``) and keeps it in workspace
    state, so it can request a run that was never seeded or has since been removed.
    Rather than show an empty dashboard (or risk a 500), an unknown/blank run id
    falls back to ``None`` — i.e. the latest data across runs.
    """
    if not run_id:  # None or "" -> latest
        return None
    exists = session.scalar(select(Run.id).where(Run.run_id == run_id).limit(1))
    return run_id if exists is not None else None


def _watchlists(
    session: Session, run_id: str | None
) -> tuple[
    dt.date | None,
    list[WatchlistEntryOut],
    list[WatchlistEntryOut],
    list[WatchlistEntryOut],
    WatchlistEntryOut | None,
]:
    """The multi-horizon opportunities (top 5 each) + the best reward:risk."""
    watchlists = watchlist_service.get_watchlists(session, run_id=run_id)
    by_h = {h.horizon: h.entries for h in watchlists.horizons}
    all_entries = [e for h in watchlists.horizons for e in h.entries]
    best: WatchlistEntryOut | None = max(
        (e for e in all_entries if e.reward_risk is not None),
        key=lambda e: e.reward_risk or 0.0,
        default=None,
    )
    return (
        watchlists.as_of,
        by_h.get("daily", [])[:_TOP_N],
        by_h.get("weekly", [])[:_TOP_N],
        by_h.get("monthly", [])[:_TOP_N],
        best,
    )


def _highest_conviction(session: Session, run_id: str | None) -> ConvictionScoreOut | None:
    stmt = select(ConvictionScore).order_by(ConvictionScore.score.desc()).limit(1)
    if run_id is not None:
        stmt = stmt.where(ConvictionScore.run_id == run_id)
    row = session.scalars(stmt).first()
    return ConvictionScoreOut.model_validate(row) if row is not None else None


def _top_sector(session: Session, run_id: str | None) -> SectorHighlightOut | None:
    """Most attractive sector (highest average conviction across candidates)."""
    candidates, _, _ = watchlist_service._load_candidates(session, run_id)
    sector_scores: dict[str, list[float]] = {}
    for cand in candidates:
        if cand.sector:
            sector_scores.setdefault(cand.sector, []).append(cand.base_conviction)
    if not sector_scores:
        return None
    # Prefer sectors with breadth (>= 2 names) so a single hot stock doesn't win.
    pool = {s: v for s, v in sector_scores.items() if len(v) >= 2} or sector_scores
    sector, scores = max(pool.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
    return SectorHighlightOut(
        sector=sector,
        avg_conviction=_finite(round(sum(scores) / len(scores), 1)) or 0.0,
        count=len(scores),
    )


def _portfolio(
    session: Session, run_id: str | None
) -> tuple[float | None, float | None, float | None]:
    """Portfolio heat / equity / daily P&L from the latest snapshot."""
    stmt = select(PortfolioSnapshot)
    if run_id is not None:
        stmt = stmt.where(PortfolioSnapshot.run_id == run_id)
    snap = session.scalars(stmt.order_by(PortfolioSnapshot.session_date.desc()).limit(1)).first()
    if snap is None:
        return None, None, None
    daily_pnl = snap.daily_pnl
    if daily_pnl is None and snap.daily_return is not None and snap.equity is not None:
        daily_pnl = snap.equity * snap.daily_return
    return _finite(snap.portfolio_heat), _finite(snap.equity), _finite(daily_pnl)


def _performance(session: Session, run_id: str | None) -> CommandPerformanceOut:
    perf = services.performance_summary(session, run_id=run_id)
    ts = perf.trade_stats
    return CommandPerformanceOut(
        n_trades=perf.n_trades,
        expectancy_r=_finite(ts.get("expectancy_r")),
        profit_factor=_finite(ts.get("profit_factor")),
        win_rate=_finite(ts.get("win_rate")),
        net_pnl=_finite(ts.get("net_profit")),
    )


def _watchlist_changes(session: Session, run_id: str | None) -> WatchlistComparisonOut | None:
    """Diff the two most recent daily generations."""
    dates = watchlist_service.watchlist_dates(session, run_id=run_id, limit=2)
    if len(dates) < 2:
        return None
    return watchlist_service.compare_watchlists(
        session, horizon="daily", base=dates[1], against=dates[0], run_id=run_id
    )


_EMPTY_PERF = CommandPerformanceOut(
    n_trades=0, expectancy_r=None, profit_factor=None, win_rate=None, net_pnl=None
)
_EMPTY_WATCHLISTS: tuple[
    dt.date | None,
    list[WatchlistEntryOut],
    list[WatchlistEntryOut],
    list[WatchlistEntryOut],
    WatchlistEntryOut | None,
] = (None, [], [], [], None)
_EMPTY_PORTFOLIO: tuple[float | None, float | None, float | None] = (None, None, None)
_EMPTY_TRIGGERED: list[LifecycleOut] = []


def command_center(session: Session, *, run_id: str | None = None) -> CommandCenterOut:
    """One aggregate. Every section is independently guarded — it never 500s."""
    run_id = _safe(session, "run_id", lambda: _effective_run_id(session, run_id), None)
    regime: RegimeOut | None = _safe(
        session, "regime", lambda: services.latest_regime(session), None
    )

    wl_as_of, daily, weekly, monthly, best_rr = _safe(
        session,
        "watchlists",
        lambda: _watchlists(session, run_id),
        _EMPTY_WATCHLISTS,
    )
    highest_conviction = _safe(
        session, "highest_conviction", lambda: _highest_conviction(session, run_id), None
    )
    top_sector = _safe(session, "top_sector", lambda: _top_sector(session, run_id), None)
    portfolio_heat, equity, daily_pnl = _safe(
        session, "portfolio", lambda: _portfolio(session, run_id), _EMPTY_PORTFOLIO
    )
    performance = _safe(session, "performance", lambda: _performance(session, run_id), _EMPTY_PERF)
    changes = _safe(session, "watchlist_changes", lambda: _watchlist_changes(session, run_id), None)
    recent_triggered = _safe(
        session,
        "recent_triggered",
        lambda: lifecycle_service.list_lifecycles(session, run_id=run_id, state="Triggered")[:8],
        _EMPTY_TRIGGERED,
    )

    as_of = wl_as_of or (regime.as_of if regime is not None else None)
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
