"""Data Health Dashboard — one read-only aggregate of pipeline freshness.

Answers "is the data flowing?" at a glance: which provider, is it connected, when
did we last pull, how old is that data, how big is the universe, how many symbols
are cached, and when did the last scan / conviction run / watchlist generation
happen. Every metric carries a traffic-light ``status`` (green/yellow/red) and the
overall status is the worst of them. A separate diagnostics view exposes the raw
provider / cache-path / database-path / timestamp values for support.

Freshness for daily data is graded in **trading sessions**, not wall-clock
minutes: a daily bar is always ≥1 calendar day old and several days old across
any weekend/holiday, so grading raw minutes would falsely flag every Monday and
post-holiday session red. ``_session_status`` (calendar-aware) keeps a
latest-completed-session bar green while still turning red on a genuine
multi-session pull outage. Pure status logic (``_session_status`` /
``_age_status`` / ``_worst``) is unit-tested directly; the aggregator only wires
the session + environment into those helpers.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import universe_service, user_settings
from momentum.data.cache import BarCache
from momentum.data.calendar import TradingCalendar
from momentum.data.schema import Timeframe
from momentum.persistence.database import get_database_url
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.repositories.scan_metadata import ScanMetadataRepository
from momentum.persistence.repositories.watchlist_entries import WatchlistRepository

GREEN = "green"
YELLOW = "yellow"
RED = "red"
_ORDER = {GREEN: 0, YELLOW: 1, RED: 2}

# Freshness windows (minutes). Daily bars tolerate weekends/holidays, so "fresh"
# is generous; beyond the stale window the scan itself is already flagged stale.
FRESH_MINUTES = 24 * 60
STALE_MINUTES = 4 * 24 * 60

# Freshness for daily data is measured in **trading sessions**, not wall-clock:
# a daily bar is always ≥1 calendar day old and several days old across every
# weekend/holiday, so grading raw wall-clock minutes would flag every Monday and
# post-holiday session red even when the data is the latest completed session.
# Measuring sessions-behind vs *now* stays green over weekends yet still catches
# a real pull outage (sessions accumulate while nothing refreshes).
FRESH_SESSIONS = 1  # newest bar is this-or-fewer sessions behind → green
AGING_SESSIONS = 3  # up to here → yellow; beyond → red
_CALENDAR = TradingCalendar()


def _worst(statuses: list[str]) -> str:
    """The most severe status in the list (green < yellow < red)."""
    if not statuses:
        return YELLOW
    return max(statuses, key=lambda s: _ORDER.get(s, 1))


def _age_status(
    minutes: float | None, *, fresh: float = FRESH_MINUTES, stale: float = STALE_MINUTES
) -> str:
    """Green if fresh, yellow if aging, red if stale or unknown (wall-clock)."""
    if minutes is None:
        return RED
    if minutes <= fresh:
        return GREEN
    if minutes <= stale:
        return YELLOW
    return RED


def _sessions_behind(ts: dt.datetime | None, now: dt.datetime) -> int | None:
    """How many completed trading sessions ``ts`` lags the latest session at ``now``.

    0 means the latest completed session (e.g. a Friday bar on Monday, or a bar
    pulled earlier today). Weekends/holidays are skipped via the trading calendar,
    so a daily bar over a long weekend is *not* counted as stale.
    """
    if ts is None:
        return None
    ref = _CALENDAR.previous_session(now.date(), inclusive=True).date()
    day = ts.date()
    if day >= ref:
        return 0
    return max(0, _CALENDAR.count_sessions(day, ref) - 1)


def _session_status(ts: dt.datetime | None, now: dt.datetime) -> str:
    """Traffic light for a daily-data timestamp, measured in trading sessions."""
    behind = _sessions_behind(ts, now)
    if behind is None:
        return RED
    if behind <= FRESH_SESSIONS:
        return GREEN
    if behind <= AGING_SESSIONS:
        return YELLOW
    return RED


def _age_minutes(ts: dt.datetime | None, now: dt.datetime) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    return max(0.0, (now - ts).total_seconds() / 60.0)


def _humanize_age(minutes: float | None) -> str:
    if minutes is None:
        return "unknown"
    if minutes < 60:
        return f"{minutes:.0f} min"
    if minutes < 24 * 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes / (24 * 60):.1f} d"


@dataclass(frozen=True, slots=True)
class HealthMetric:
    key: str
    label: str
    value: str | None
    status: str
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "detail": self.detail,
        }


def _cache_root() -> str:
    return os.environ.get("MRP_BAR_CACHE", "data/bars")


def _latest_conviction(session: Session) -> tuple[dt.date | None, dt.datetime | None, str | None]:
    """Newest conviction batch: ``(as_of, ts, run_id)`` or all-None if none exist.

    Honours the active data-mode filter, so in production demo rows are invisible
    here — the dashboard reports *live* conviction only, never demo.
    """
    row = session.scalars(
        select(ConvictionScore).order_by(ConvictionScore.id.desc()).limit(1)
    ).first()
    if row is None:
        return None, None, None
    return row.as_of, row.ts, row.run_id


def data_health(
    session: Session,
    *,
    provider_name: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Aggregate the pipeline's freshness into traffic-light metrics."""
    now = now or dt.datetime.now(tz=dt.UTC)
    provider = provider_name or user_settings.read_provider()
    mode = user_settings.read_data_mode()

    meta = ScanMetadataRepository(session).latest()
    pull_ts = meta.pull_timestamp if meta else None
    pull_age = (
        meta.data_age_minutes
        if (meta and meta.data_age_minutes is not None)
        else _age_minutes(pull_ts, now)
    )

    # Freshness of the newest bar / last pull, measured in trading sessions vs now
    # (weekend/holiday-aware, but a genuine pull outage still trips it).
    bar_status = _session_status(meta.bar_timestamp if meta else None, now)
    pull_status = _session_status(pull_ts, now)
    behind = _sessions_behind(meta.bar_timestamp if meta else None, now)

    # Connection: green while pulls are landing on schedule; degrades only when the
    # last pull is genuinely several sessions old (a real outage) or the scan
    # flagged the data stale — never merely because it is a Monday.
    if meta is None:
        conn_status, conn_value = RED, "never pulled"
    elif pull_status == RED:
        conn_status, conn_value = RED, "no recent pull"
    elif pull_status == YELLOW or meta.stale:
        conn_status, conn_value = YELLOW, "degraded"
    else:
        conn_status, conn_value = GREEN, "connected"

    universe = universe_service.resolve_selected(session)
    cached = len(BarCache(_cache_root()).symbols(Timeframe.DAY))

    conv_as_of, conv_ts, conv_run = _latest_conviction(session)
    if conv_as_of is None:
        conv_status, conv_value = RED, "No live conviction data available"
    else:
        conv_status = _session_status(conv_ts, now) if conv_ts else YELLOW
        conv_value = f"{conv_as_of.isoformat()} ({conv_run or 'live'})"

    wl_date = WatchlistRepository(session).latest_date()
    wl_status = (
        RED
        if wl_date is None
        else _session_status(dt.datetime.combine(wl_date, dt.time(), tzinfo=dt.UTC), now)
    )

    age_detail = (
        None
        if behind is None
        else "latest completed trading session"
        if behind <= FRESH_SESSIONS
        else f"{behind} trading sessions behind"
    )

    metrics = [
        HealthMetric("provider", "Current Provider", provider, GREEN, f"data mode: {mode}"),
        HealthMetric("connection", "Connection Status", conn_value, conn_status),
        HealthMetric(
            "last_pull",
            "Last Successful Pull",
            pull_ts.isoformat() if pull_ts else None,
            pull_status,
        ),
        HealthMetric(
            "data_age",
            "Data Age",
            _humanize_age(pull_age),
            bar_status,
            detail=age_detail,
        ),
        HealthMetric(
            "universe",
            "Universe Size",
            f"{universe.label}: {len(universe.symbols)}",
            GREEN if universe.symbols else RED,
        ),
        HealthMetric(
            "cached",
            "Symbols Cached",
            str(cached),
            GREEN if cached > 0 else YELLOW,
        ),
        HealthMetric(
            "latest_scan",
            "Latest Scan",
            meta.scan_id if meta else None,
            GREEN if meta and not meta.stale else (YELLOW if meta else RED),
            detail=f"{meta.symbol_count} symbols" if meta else None,
        ),
        HealthMetric("latest_conviction", "Latest Conviction Run", conv_value, conv_status),
        HealthMetric(
            "latest_watchlist",
            "Latest Watchlist Generation",
            wl_date.isoformat() if wl_date else None,
            wl_status,
        ),
    ]

    return {
        "status": _worst([m.status for m in metrics]),
        "data_mode": mode,
        "provider": provider,
        "generated_at": now.isoformat(),
        "metrics": [m.to_dict() for m in metrics],
    }


def diagnostics(
    session: Session,
    *,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Raw diagnostic values behind the dashboard (View Raw Diagnostics)."""
    provider = provider_name or user_settings.read_provider()
    meta = ScanMetadataRepository(session).latest()
    cache = BarCache(_cache_root())
    conv_as_of, conv_ts, conv_run = _latest_conviction(session)
    return {
        "provider": provider,
        "data_mode": user_settings.read_data_mode(),
        "cache_path": str(cache.root),
        "database_path": get_database_url(),
        "symbols_cached": len(cache.symbols(Timeframe.DAY)),
        "latest_bar_timestamp": meta.bar_timestamp.isoformat()
        if (meta and meta.bar_timestamp)
        else None,
        "latest_scan_id": meta.scan_id if meta else None,
        "latest_scan_timestamp": meta.pull_timestamp.isoformat() if meta else None,
        "scan_stale": meta.stale if meta else None,
        "data_age_minutes": meta.data_age_minutes if meta else None,
        "latest_conviction_as_of": conv_as_of.isoformat() if conv_as_of else None,
        "latest_conviction_run_id": conv_run,
        "latest_conviction_ts": conv_ts.isoformat() if conv_ts else None,
        "latest_watchlist_date": (
            d.isoformat() if (d := WatchlistRepository(session).latest_date()) else None
        ),
    }
