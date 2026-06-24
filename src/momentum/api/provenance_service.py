"""Data-lineage / provenance for every displayed surface.

Answers, for whatever run a screen is showing: **where** the data came from (source
provider), **when** it was fetched (fetch timestamp + data age), the **run_id** it
belongs to, **when** each screen's rows were generated, and whether it is **demo or
live** — so there is never hidden fallback behaviour. One call returns the run-level
source/fetch facts plus a per-screen generation timestamp + row count.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from momentum.api import user_settings
from momentum.api.services import resolve_active_run_id
from momentum.persistence.models.candidate_analog import CandidateAnalog
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.models.watchlist_entry import WatchlistEntryRow
from momentum.persistence.repositories.scan_metadata import ScanMetadataRepository

DEMO_RUN_ID = "demo"


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _screen(session: Session, model: Any, run_id: str, ts_col: Any) -> dict[str, Any]:
    count = int(
        session.scalar(select(func.count()).select_from(model).where(model.run_id == run_id)) or 0
    )
    generated = session.scalar(select(func.max(ts_col)).where(model.run_id == run_id))
    gen_iso = generated.isoformat() if isinstance(generated, dt.datetime) else None
    return {"rows": count, "generation_timestamp": gen_iso}


def provenance(session: Session, *, run_id: str | None = None) -> dict[str, Any]:
    """Provenance for the active run (or an explicit run_id)."""
    run_id = run_id or resolve_active_run_id(session)
    if run_id is None:
        return {
            "run_id": None,
            "mode": "none",
            "source_provider": None,
            "fetch_timestamp": None,
            "bar_timestamp": None,
            "data_age_minutes": None,
            "stale": None,
            "screens": {},
        }

    is_demo = run_id == DEMO_RUN_ID
    meta = ScanMetadataRepository(session).by_scan_id(run_id)
    if is_demo:
        source = "demo seed"
        fetch_ts = bar_ts = None
        data_age = None
        stale: bool | None = None
    else:
        source = meta.provider if meta is not None else user_settings.read_provider()
        fetch_ts = _iso(meta.pull_timestamp) if meta is not None else None
        bar_ts = _iso(meta.bar_timestamp) if meta is not None else None
        data_age = meta.data_age_minutes if meta is not None else None
        stale = meta.stale if meta is not None else None

    screens = {
        # The scan rows were "generated" at fetch time.
        "scan": {
            **_screen(session, ScanResult, run_id, ScanResult.created_at),
            "generation_timestamp": fetch_ts,
        },
        "conviction": _screen(session, ConvictionScore, run_id, ConvictionScore.ts),
        "watchlists": _screen(session, WatchlistEntryRow, run_id, WatchlistEntryRow.generated_at),
        "trade_plans": _screen(session, TradePlan, run_id, TradePlan.generated_at),
        "analogs": _screen(session, CandidateAnalog, run_id, CandidateAnalog.generated_at),
        # Options recommendations are derived live from the scan (not persisted).
        "options": {"rows": None, "generation_timestamp": fetch_ts},
    }

    return {
        "run_id": run_id,
        "mode": "demo" if is_demo else "live",
        "source_provider": source,
        "fetch_timestamp": fetch_ts,
        "bar_timestamp": bar_ts,
        "data_age_minutes": data_age,
        "stale": stale,
        "screens": screens,
    }
