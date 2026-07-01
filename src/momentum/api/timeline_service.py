"""Scan timeline — build/persist immutable snapshots, then derive deltas,
alerts, activities and performance stats from each completed scan.

``record_scan`` is the single post-scan hook: it freezes the scan's full
research state as a :class:`ScanSnapshot`, diffs it against the previous
snapshot (the conviction delta engine), persists every changed metric as an
append-only ``scan_deltas`` row, turns the important ones into deduplicated
``alerts`` and the meaningful ones into ``activities``, and records the scan's
performance row (with a degradation alert when the scan ran far slower than
its recent median).
"""

from __future__ import annotations

import datetime as dt
import os
import resource
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.persistence.models.activity import Activity
from momentum.persistence.models.alert import Alert
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.scan_delta import ScanDelta
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.scan_snapshot import ScanSnapshot
from momentum.persistence.models.scan_stat import ScanStat
from momentum.persistence.models.trade_evaluation import TradeEvaluation
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.models.watchlist_entry import WatchlistEntryRow
from momentum.persistence.repositories.pulse import (
    ActivityRepository,
    AlertRepository,
    ScanDeltaRepository,
    ScanSnapshotRepository,
    ScanStatRepository,
)
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.timeline import derive_activities, derive_alerts, diff_snapshots

# A scan slower than this multiple of its recent median is "degraded".
DEGRADED_FACTOR = 2.0
DEGRADED_MIN_SAMPLES = 5

# Watchlist symbols kept per horizon in the snapshot (rank order).
WATCHLIST_DEPTH = 10


# --------------------------------------------------------------------------- #
# Snapshot building
# --------------------------------------------------------------------------- #
def build_snapshot(
    session: Session,
    *,
    run_id: str,
    ts: dt.datetime,
    market_state: str | None,
) -> dict[str, Any]:
    """Freeze the scan's full research state as one JSON-safe payload."""
    conviction_by_symbol = {
        c.symbol: c
        for c in session.scalars(select(ConvictionScore).where(ConvictionScore.run_id == run_id))
    }
    candidates: dict[str, dict[str, Any]] = {}
    sector_scores: dict[str, list[float]] = {}
    for row in session.scalars(select(ScanResult).where(ScanResult.run_id == run_id)):
        conviction = conviction_by_symbol.get(row.symbol)
        candidates[row.symbol] = {
            "price": row.price,
            "conviction": conviction.score if conviction else None,
            "momentum": row.momentum_score,
            "relative_volume": row.relative_volume,
            "sector_rs": row.sector_rs,
            "atr": row.atr,
            "rank": row.rank,
            "sector": row.sector,
        }
        if row.sector and row.sector_rs is not None:
            sector_scores.setdefault(row.sector, []).append(row.sector_rs)

    watchlists: dict[str, list[str]] = {}
    stmt = (
        select(WatchlistEntryRow)
        .where(WatchlistEntryRow.run_id == run_id)
        .order_by(WatchlistEntryRow.horizon, WatchlistEntryRow.rank)
    )
    for entry in session.scalars(stmt):
        bucket = watchlists.setdefault(entry.horizon, [])
        if len(bucket) < WATCHLIST_DEPTH:
            bucket.append(entry.symbol)

    # Tracked-trade state: latest evaluation per open trade (health / action /
    # price vs stop + next target) — feeds health deltas and stop/target alerts.
    trades: dict[str, dict[str, Any]] = {}
    for trade in TrackedTradeRepository(session).open_trades():
        latest = session.scalars(
            select(TradeEvaluation)
            .where(TradeEvaluation.trade_uid == trade.trade_uid)
            .order_by(TradeEvaluation.evaluated_at.desc(), TradeEvaluation.id.desc())
            .limit(1)
        ).first()
        next_target: float | None = None
        for target in trade.targets or []:
            price_value = target.get("price") if isinstance(target, dict) else None
            if isinstance(price_value, (int, float)):
                next_target = (
                    float(price_value)
                    if next_target is None
                    else min(next_target, float(price_value))
                )
        trades[trade.symbol] = {
            "health": (
                latest.health_score
                if latest is not None and latest.health_score is not None
                else (latest.thesis_strength if latest is not None else None)
            ),
            "action": latest.action if latest is not None else None,
            "price": latest.price if latest is not None else None,
            "stop": trade.stop_price,
            "next_target": next_target,
        }
        # Trade health also rides on the candidate map so health deltas appear
        # beside conviction deltas for scanned symbols.
        if trade.symbol in candidates:
            candidates[trade.symbol]["health"] = trades[trade.symbol]["health"]

    regime_row = session.scalars(
        select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)
    ).first()

    plans = sum(1 for _ in session.scalars(select(TradePlan.id).where(TradePlan.run_id == run_id)))

    return {
        "ts": ts.isoformat(),
        "run_id": run_id,
        "market_state": market_state,
        "regime": {
            "regime": regime_row.regime if regime_row else None,
            "breadth": regime_row.breadth if regime_row else None,
        },
        "candidates": candidates,
        "watchlists": watchlists,
        "trades": trades,
        "sectors": {
            sector: round(sum(values) / len(values), 4) for sector, values in sector_scores.items()
        },
        "command_center": {
            "candidates": len(candidates),
            "open_trades": len(trades),
            "trade_plans": plans,
            "top_conviction": sorted(
                (
                    (symbol, c["conviction"])
                    for symbol, c in candidates.items()
                    if c["conviction"] is not None
                ),
                key=lambda pair: -pair[1],
            )[:5],
        },
    }


# --------------------------------------------------------------------------- #
# The post-scan hook
# --------------------------------------------------------------------------- #
def record_scan(
    session: Session,
    *,
    run_id: str,
    ts: dt.datetime,
    market_state: str | None,
    duration_ms: float,
    symbols_processed: int,
    symbols_failed: int,
    provider_latency_ms: float | None,
    db_writes: int,
    convictions_generated: int,
    watchlists_generated: int,
    incremental: dict[str, Any] | None = None,
    cpu_percent: float | None = None,
) -> dict[str, int]:
    """Snapshot + diff + alerts + activities + stats for one completed scan. Commits."""
    snapshots = ScanSnapshotRepository(session)
    previous = snapshots.latest()
    payload = build_snapshot(session, run_id=run_id, ts=ts, market_state=market_state)
    snapshots.add(
        ScanSnapshot(
            scan_ts=ts,
            run_id=run_id,
            market_state=market_state,
            candidates=len(payload["candidates"]),
            payload=payload,
        )
    )

    deltas = diff_snapshots(previous.payload, payload) if previous is not None else []
    delta_repo = ScanDeltaRepository(session)
    prev_ts = previous.scan_ts if previous is not None else None
    for record in deltas:
        delta_repo.add(
            ScanDelta(scan_ts=ts, run_id=run_id, prev_scan_ts=prev_ts, **record.to_dict())
        )

    alert_specs = derive_alerts(deltas, new_snapshot=payload)
    alert_repo = AlertRepository(session)
    existing = alert_repo.existing_keys([a.dedupe_key for a in alert_specs])
    alerts_written = 0
    for spec in alert_specs:
        if spec.dedupe_key in existing:
            continue  # never duplicate an alert
        existing.add(spec.dedupe_key)
        alert_repo.add(Alert(ts=ts, run_id=run_id, **spec.to_dict()))
        alerts_written += 1

    activity_repo = ActivityRepository(session)
    activities = derive_activities(deltas)
    for entry in activities:
        activity_repo.add(
            Activity(
                ts=ts,
                run_id=run_id,
                symbol=entry.symbol,
                category=entry.category,
                text=entry.text,
                payload=entry.payload,
            )
        )

    stats_repo = ScanStatRepository(session)
    median = stats_repo.median_duration_ms()
    degraded = (
        median is not None
        and stats_repo.count_all() >= DEGRADED_MIN_SAMPLES
        and duration_ms > DEGRADED_FACTOR * median
    )
    incremental = incremental or {}
    stats_repo.add(
        ScanStat(
            scan_ts=ts,
            run_id=run_id,
            duration_ms=duration_ms,
            symbols_processed=symbols_processed,
            symbols_failed=symbols_failed,
            provider_latency_ms=provider_latency_ms,
            db_writes=db_writes,
            convictions_generated=convictions_generated,
            watchlists_generated=watchlists_generated,
            alerts_generated=alerts_written,
            deltas_generated=len(deltas),
            activities_generated=len(activities),
            symbols_skipped=incremental.get("symbols_skipped"),
            symbols_recomputed=incremental.get("symbols_recomputed"),
            cache_hit_rate=incremental.get("cache_hit_rate"),
            memory_mb=_memory_mb(),
            cpu_percent=cpu_percent,
            degraded=bool(degraded),
        )
    )
    if degraded and median is not None:
        key = f"performance:{ts.isoformat()}"
        if not alert_repo.existing_keys([key]):
            alert_repo.add(
                Alert(
                    ts=ts,
                    run_id=run_id,
                    symbol=None,
                    severity="warning",
                    kind="performance",
                    title="Scan performance degraded",
                    description=(
                        f"scan took {duration_ms:.0f} ms vs a recent median of {median:.0f} ms"
                    ),
                    dedupe_key=key,
                )
            )
            alerts_written += 1

    session.commit()
    return {
        "snapshot": 1,
        "deltas": len(deltas),
        "alerts": alerts_written,
        "activities": len(activities),
    }


def _memory_mb() -> float:
    """Peak RSS of this process in MB (Linux reports ru_maxrss in KB)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname == "Darwin":  # macOS reports bytes
        return round(usage / (1024.0 * 1024.0), 1)
    return round(usage / 1024.0, 1)


# --------------------------------------------------------------------------- #
# Reads: timeline / replay / diff
# --------------------------------------------------------------------------- #
def list_snapshots(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    return [s.to_dict() for s in ScanSnapshotRepository(session).recent(limit=limit)]


def get_snapshot(session: Session, snapshot_id: int) -> dict[str, Any] | None:
    row = ScanSnapshotRepository(session).get(snapshot_id)
    return row.to_dict(include_payload=True) if row is not None else None


def diff_two(session: Session, a_id: int, b_id: int) -> list[dict[str, Any]] | None:
    """Diff any two stored snapshots (a = earlier, b = later)."""
    repo = ScanSnapshotRepository(session)
    a = repo.get(a_id)
    b = repo.get(b_id)
    if a is None or b is None:
        return None
    return [d.to_dict() for d in diff_snapshots(a.payload, b.payload)]
