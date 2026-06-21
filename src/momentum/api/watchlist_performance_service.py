"""Service layer for watchlist-performance tracking.

Two responsibilities:

* **Track** — given freshly pulled bars, turn every stored watchlist entry into a
  forward-performance row (1d/1w/1m returns + MFE/MAE) and upsert it (idempotent
  per generation). Bars are injected, so this is offline-testable.
* **Read** — assemble the scorecards / prediction-quality report and the tracked
  entries for the dashboard.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from momentum.api.schemas import WatchlistPerfEntryOut, WatchlistPerformanceReportOut
from momentum.persistence.models.watchlist_performance import WatchlistPerformance
from momentum.persistence.repositories.watchlist_entries import WatchlistRepository
from momentum.persistence.repositories.watchlist_performance import (
    WatchlistPerformanceRepository,
)
from momentum.watchlist import default_config as watchlist_default_config
from momentum.watchlist_performance import (
    EntryPrediction,
    PerformanceRecord,
    build_report,
    default_config,
    track_entry,
)


def _horizon_order() -> list[tuple[str, str]]:
    return [(h.key, h.label) for h in watchlist_default_config().horizons]


def track_performance(
    session: Session,
    bars_by_symbol: dict[str, pd.DataFrame],
    *,
    run_id: str | None = None,
    incomplete_only: bool = False,
) -> dict[str, Any]:
    """Track stored watchlist entries against ``bars_by_symbol`` and upsert results.

    ``incomplete_only`` skips generations whose 1-month window already elapsed (so a
    routine re-run only re-touches still-maturing rows).
    """
    cfg = default_config()
    perf_repo = WatchlistPerformanceRepository(session)
    entries = _all_entries(session, run_id)
    done_keys = _complete_keys(perf_repo, run_id) if incomplete_only else set()

    records: list[PerformanceRecord] = []
    for row in entries:
        key = (row.run_id, row.as_of, row.horizon, row.symbol)
        if incomplete_only and key in done_keys:
            continue
        bars = bars_by_symbol.get(row.symbol)
        if bars is None or bars.empty:
            continue
        rec = track_entry(_prediction(row), bars, cfg)
        if rec is not None:
            records.append(rec)

    n = perf_repo.upsert_many(records)
    session.commit()
    return {
        "tracked": n,
        "symbols": len({r.symbol for r in records}),
        "generations": len({(r.run_id, r.as_of) for r in records}),
        "complete": sum(1 for r in records if r.complete),
    }


def performance_report(
    session: Session, *, run_id: str | None = None
) -> WatchlistPerformanceReportOut:
    """Scorecards + prediction-quality, per horizon (the comparison dashboard)."""
    rows = WatchlistPerformanceRepository(session).all_records(run_id)
    records = [_to_record(r) for r in rows]
    report = build_report(records, default_config(), horizon_order=_horizon_order())
    return WatchlistPerformanceReportOut(**_finite(report.to_dict()))


def performance_entries(
    session: Session, *, horizon: str | None = None, run_id: str | None = None
) -> list[WatchlistPerfEntryOut]:
    """Tracked entries (optionally one horizon), newest generation first."""
    repo = WatchlistPerformanceRepository(session)
    rows = repo.for_horizon(horizon, run_id=run_id) if horizon else repo.all_records(run_id)
    return [WatchlistPerfEntryOut.model_validate(r) for r in rows]


def tracking_symbols(session: Session, run_id: str | None = None) -> list[str]:
    """Distinct symbols across stored watchlist entries (what to pull bars for)."""
    return sorted({row.symbol for row in _all_entries(session, run_id)})


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _all_entries(session: Session, run_id: str | None) -> list[Any]:
    repo = WatchlistRepository(session)
    out: list[Any] = []
    for as_of in repo.dates(run_id, limit=365):
        out.extend(repo.for_date(as_of, run_id=run_id))
    return out


def _complete_keys(
    repo: WatchlistPerformanceRepository, run_id: str | None
) -> set[tuple[str | None, dt.date, str, str]]:
    complete = {
        (r.run_id, r.as_of, r.horizon, r.symbol) for r in repo.all_records(run_id) if r.complete
    }
    return complete


def _prediction(row: Any) -> EntryPrediction:
    return EntryPrediction(
        run_id=row.run_id,
        as_of=row.as_of,
        horizon=row.horizon,
        horizon_label=row.horizon_label,
        symbol=row.symbol,
        conviction=row.conviction,
        rank=row.rank,
        expected_move_pct=row.expected_move_pct,
        horizon_days=row.horizon_days,
        watchlist_entry_id=row.id,
    )


def _to_record(row: WatchlistPerformance) -> PerformanceRecord:
    return PerformanceRecord(
        run_id=row.run_id,
        as_of=row.as_of,
        horizon=row.horizon,
        horizon_label=row.horizon_label,
        symbol=row.symbol,
        conviction=row.conviction,
        rank=row.rank,
        expected_move_pct=row.expected_move_pct,
        horizon_days=row.horizon_days,
        watchlist_entry_id=row.watchlist_entry_id,
        reference_price=row.reference_price,
        ret_1d=row.ret_1d,
        ret_1w=row.ret_1w,
        ret_1m=row.ret_1m,
        mfe=row.mfe,
        mae=row.mae,
        bars_tracked=row.bars_tracked,
        complete=row.complete,
        last_price=row.last_price,
        last_tracked_date=row.last_tracked_date,
        model_version=row.model_version,
        config_hash=row.config_hash,
    )


def _finite(payload: dict[str, Any]) -> dict[str, Any]:
    """Null out any non-finite floats before serialization."""

    def clean(value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return {k: clean(v) for k, v in payload.items()}
