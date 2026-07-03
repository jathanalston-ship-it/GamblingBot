"""Gathers the certification inputs from the live system and grades them.

Everything is derived from surfaces that already exist — ``scan_stats``
(coverage, memory, latency), ``runs`` (API failures), ``trades`` (opened/
closed/duplicates), ``alerts`` (alert volume + severities),
``market_data_provenance`` (provider failures), the automation-state crash
history and a live ``PRAGMA integrity_check`` — then handed to the pure
:mod:`momentum.certification` engine. No new tables; the report is always
recomputable from the record.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from momentum.certification import CertificationInputs, evaluate
from momentum.certification.config import CertificationConfig, default_config
from momentum.persistence.models import Alert, Run, Trade
from momentum.persistence.models.market_data_provenance import MarketDataProvenance
from momentum.persistence.models.scan_stat import ScanStat

_log = logging.getLogger(__name__)


def _utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def _database_ok(session: Session) -> bool:
    try:
        verdict = session.execute(text("PRAGMA integrity_check")).scalar()
        return str(verdict).lower() == "ok"
    except Exception:  # noqa: BLE001 — an unreadable database is NOT ok
        _log.warning("integrity check failed", exc_info=True)
        return False


def _duplicate_trades(session: Session) -> int:
    """Symbols holding >1 open journal trade + identical (symbol, entry) rows."""
    over_open = session.execute(
        select(Trade.symbol, func.count(Trade.id))
        .where(Trade.status == "open")
        .group_by(Trade.symbol)
        .having(func.count(Trade.id) > 1)
    ).all()
    duplicates = sum(count - 1 for _symbol, count in over_open)
    identical = session.execute(
        select(Trade.symbol, Trade.entry_ts, func.count(Trade.id))
        .group_by(Trade.symbol, Trade.entry_ts)
        .having(func.count(Trade.id) > 1)
    ).all()
    duplicates += sum(count - 1 for _symbol, _ts, count in identical)
    return int(duplicates)


def gather_inputs(
    session: Session,
    *,
    now: dt.datetime | None = None,
    config: CertificationConfig | None = None,
) -> CertificationInputs:
    from momentum.api import automation_state

    cfg = config or default_config()
    when = now or dt.datetime.now(tz=dt.UTC)
    window_start = when - dt.timedelta(days=cfg.window_days)

    stats = list(
        session.scalars(
            select(ScanStat).where(ScanStat.scan_ts >= window_start).order_by(ScanStat.scan_ts)
        )
    )
    scan_timestamps = tuple(_utc(s.scan_ts) for s in stats)
    memory_series = tuple(s.memory_mb for s in stats if s.memory_mb is not None)
    durations = tuple(s.duration_ms for s in stats)
    degraded = sum(1 for s in stats if s.degraded)

    trades_opened = (
        session.execute(
            select(func.count(Trade.id)).where(Trade.entry_ts >= window_start)
        ).scalar_one()
        or 0
    )
    trades_closed = (
        session.execute(
            select(func.count(Trade.id)).where(
                Trade.exit_ts.is_not(None), Trade.exit_ts >= window_start
            )
        ).scalar_one()
        or 0
    )
    alerts_total = (
        session.execute(select(func.count(Alert.id)).where(Alert.ts >= window_start)).scalar_one()
        or 0
    )
    alerts_critical = (
        session.execute(
            select(func.count(Alert.id)).where(
                Alert.ts >= window_start, Alert.severity == "critical"
            )
        ).scalar_one()
        or 0
    )
    alerts_warning = (
        session.execute(
            select(func.count(Alert.id)).where(
                Alert.ts >= window_start, Alert.severity == "warning"
            )
        ).scalar_one()
        or 0
    )
    failed_runs = (
        session.execute(
            select(func.count(Run.id)).where(Run.status == "failed", Run.started_at >= window_start)
        ).scalar_one()
        or 0
    )
    provider_failures = (
        session.execute(
            select(func.count(MarketDataProvenance.id)).where(
                MarketDataProvenance.request_timestamp >= window_start,
                MarketDataProvenance.error.is_not(None),
            )
        ).scalar_one()
        or 0
    )

    crash_timestamps: list[dt.datetime] = []
    for record in automation_state.recoveries(since=window_start):
        try:
            crash_timestamps.append(_utc(dt.datetime.fromisoformat(str(record["recovered_at"]))))
        except (KeyError, ValueError):
            continue

    return CertificationInputs(
        now=when,
        scan_timestamps=scan_timestamps,
        memory_series=memory_series,
        scan_durations_ms=durations,
        crash_timestamps=tuple(crash_timestamps),
        trades_opened=int(trades_opened),
        trades_closed=int(trades_closed),
        alerts_generated=int(alerts_total),
        errors=int(failed_runs + alerts_critical),
        warnings=int(alerts_warning + degraded),
        api_failures=int(failed_runs),
        provider_failures=int(provider_failures),
        duplicate_trades=_duplicate_trades(session),
        database_ok=_database_ok(session),
        orphan_protection_active=bool(os.environ.get("MRP_PARENT_PID")),
    )


def certification_report(
    session: Session,
    *,
    now: dt.datetime | None = None,
    config: CertificationConfig | None = None,
) -> dict[str, Any]:
    cfg = config or default_config()
    report = evaluate(gather_inputs(session, now=now, config=cfg), cfg)
    return report.to_dict()
