"""Service layer for multi-horizon watchlists: generate, read and compare.

Generation joins the latest conviction scores with their scan context (sector,
price, ATR), runs the pure :class:`WatchlistEngine`, and persists every entry so
watchlists can be queried by date and compared over time.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api.schemas import (
    WatchlistComparisonOut,
    WatchlistEntryOut,
    WatchlistMoveOut,
    WatchlistOut,
    WatchlistSetOut,
)
from momentum.persistence.models import ConvictionScore, ScanResult
from momentum.persistence.repositories.watchlist_entries import WatchlistRepository
from momentum.watchlist import WatchlistCandidate, WatchlistEngine, default_config


def _ordered_horizons() -> list[tuple[str, str]]:
    return [(h.key, h.label) for h in default_config().horizons]


def _conviction_factors(row: ConvictionScore) -> dict[str, float]:
    """Stored normalized component scores, keyed by the engine's factor names."""
    mapping: dict[str, float | None] = {
        "market_regime": row.regime_score,
        "sector_strength": row.sector_strength,
        "relative_volume": row.relative_volume,
        "distance_to_ath": row.distance_to_ath,
        "trend_strength": row.trend_strength,
        "breadth": row.breadth,
        "momentum_score": row.momentum_score,
        "historical_similar_setups": row.historical_edge,
    }
    return {k: v for k, v in mapping.items() if v is not None}


def _load_candidates(
    session: Session, run_id: str | None
) -> tuple[list[WatchlistCandidate], dt.date | None]:
    """Build candidates from the latest conviction scores + their scan context."""
    cstmt = select(ConvictionScore)
    if run_id is not None:
        cstmt = cstmt.where(ConvictionScore.run_id == run_id)
    conv_rows = list(session.scalars(cstmt.order_by(ConvictionScore.as_of.desc())))
    if not conv_rows:
        return [], None
    as_of = conv_rows[0].as_of

    conviction: dict[str, ConvictionScore] = {}
    for r in conv_rows:
        if r.as_of == as_of and r.symbol not in conviction:
            conviction[r.symbol] = r

    sstmt = select(ScanResult)
    if run_id is not None:
        sstmt = sstmt.where(ScanResult.run_id == run_id)
    scans: dict[str, ScanResult] = {}
    for s in session.scalars(sstmt.order_by(ScanResult.as_of.desc())):
        scans.setdefault(s.symbol, s)

    candidates: list[WatchlistCandidate] = []
    for symbol, c in conviction.items():
        scan = scans.get(symbol)
        candidates.append(
            WatchlistCandidate(
                symbol=symbol,
                base_conviction=c.score,
                band=c.band,
                factors=_conviction_factors(c),
                sector=scan.sector if scan else None,
                price=scan.price if scan else None,
                atr=scan.atr if scan else None,
            )
        )
    return candidates, as_of


def generate_watchlists(
    session: Session, *, run_id: str | None = None, as_of: dt.date | None = None
) -> WatchlistSetOut:
    """Generate, persist (idempotent per date/run) and return the watchlist set."""
    candidates, conv_as_of = _load_candidates(session, run_id)
    target = as_of or conv_as_of or dt.date.today()
    produced = WatchlistEngine().generate(candidates, as_of=target, run_id=run_id)
    flat = [entry for entries in produced.values() for entry in entries]
    WatchlistRepository(session).replace_for(as_of=target, run_id=run_id, entries=flat)
    session.commit()
    return get_watchlists(session, run_id=run_id, as_of=target)


def get_watchlists(
    session: Session, *, run_id: str | None = None, as_of: dt.date | None = None
) -> WatchlistSetOut:
    """The full Today/Week/Month set for a date (latest if unspecified)."""
    repo = WatchlistRepository(session)
    target = as_of or repo.latest_date(run_id)
    horizons: list[WatchlistOut] = []
    grouped: dict[str, list[WatchlistEntryOut]] = {}
    if target is not None:
        for row in repo.for_date(target, run_id=run_id):
            grouped.setdefault(row.horizon, []).append(WatchlistEntryOut.model_validate(row))
    for key, label in _ordered_horizons():
        entries = sorted(grouped.get(key, []), key=lambda e: e.rank)
        horizons.append(WatchlistOut(horizon=key, label=label, as_of=target, entries=entries))
    return WatchlistSetOut(run_id=run_id, as_of=target, horizons=horizons)


def get_watchlist(
    session: Session,
    horizon: str,
    *,
    run_id: str | None = None,
    as_of: dt.date | None = None,
) -> WatchlistOut:
    """One horizon's ranked watchlist for a date."""
    repo = WatchlistRepository(session)
    target = as_of or repo.latest_date(run_id)
    label = dict(_ordered_horizons()).get(horizon, horizon)
    entries: list[WatchlistEntryOut] = []
    if target is not None:
        rows = repo.for_date(target, horizon=horizon, run_id=run_id)
        entries = [WatchlistEntryOut.model_validate(r) for r in rows]
    return WatchlistOut(horizon=horizon, label=label, as_of=target, entries=entries)


def watchlist_dates(
    session: Session, *, run_id: str | None = None, limit: int = 60
) -> list[dt.date]:
    """Distinct generation dates, newest first (the history selector)."""
    return WatchlistRepository(session).dates(run_id, limit=limit)


def compare_watchlists(
    session: Session,
    *,
    horizon: str,
    base: dt.date,
    against: dt.date,
    run_id: str | None = None,
) -> WatchlistComparisonOut:
    """Diff two generations of one horizon: added / removed / rank moves."""
    repo = WatchlistRepository(session)
    base_by = {r.symbol: r for r in repo.for_date(base, horizon=horizon, run_id=run_id)}
    against_by = {r.symbol: r for r in repo.for_date(against, horizon=horizon, run_id=run_id)}

    added = [WatchlistEntryOut.model_validate(r) for s, r in against_by.items() if s not in base_by]
    removed = [
        WatchlistEntryOut.model_validate(r) for s, r in base_by.items() if s not in against_by
    ]
    moved: list[WatchlistMoveOut] = []
    for symbol, br in base_by.items():
        ar = against_by.get(symbol)
        if ar is None:
            continue
        moved.append(
            WatchlistMoveOut(
                symbol=symbol,
                base_rank=br.rank,
                against_rank=ar.rank,
                rank_change=br.rank - ar.rank,  # positive = moved up toward rank 1
                base_conviction=br.conviction,
                against_conviction=ar.conviction,
                conviction_change=round(ar.conviction - br.conviction, 2),
            )
        )
    added.sort(key=lambda e: e.rank)
    removed.sort(key=lambda e: e.rank)
    moved.sort(key=lambda m: m.against_rank)
    return WatchlistComparisonOut(
        horizon=horizon,
        base_date=base,
        against_date=against,
        added=added,
        removed=removed,
        moved=moved,
    )
