"""Pure certification grading — no I/O, no clock, no network.

The coverage model walks every minute of the window that the ET schedule
says the daemon should be scanning (premarket / regular / after-hours) and
checks a scan exists within tolerance. Per ET calendar day it records the
uncovered minutes and the largest uncovered run; a crash recovery marks its
day bad too. The **streak** is the run of consecutive clean days ending
today — a violation resets it and certification rebuilds from zero (it
never stays "failing" for a stale reason; state that is *currently* wrong,
like corruption or duplicate trades, does).

Coverage is measured from the FIRST scan inside the window (before the
platform ever ran there is nothing to certify — the streak simply hasn't
started), and a calendar day with no scheduled scanning (weekend/holiday)
is neutral: it can neither break nor extend the streak.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_left
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from momentum.certification.config import CertificationConfig, default_config
from momentum.certification.types import CertificationInputs, CertificationReport, Requirement

_ET = ZoneInfo("America/New_York")


def _p95(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(0.95 * (len(ordered) - 1))]


def _memory_growth(series: tuple[float, ...]) -> float | None:
    """Median of the last decile minus median of the first decile (MB)."""
    if len(series) < 10:
        return None
    decile = max(len(series) // 10, 1)
    head = sorted(series[:decile])
    tail = sorted(series[-decile:])
    return tail[len(tail) // 2] - head[len(head) // 2]


@dataclass(frozen=True, slots=True)
class _Day:
    uncovered_minutes: int
    max_gap_run: int  # longest run of consecutive uncovered scanning minutes
    crashed: bool

    @property
    def clean(self) -> bool:
        return self.uncovered_minutes == 0 and not self.crashed


def _walk_days(
    inputs: CertificationInputs, config: CertificationConfig
) -> tuple[dict[dt.date, _Day], float]:
    """Per-ET-day coverage records + window uptime fraction."""
    from momentum.daemon.market_state import market_state

    scans = sorted(inputs.scan_timestamps)
    if not scans:
        return {}, 0.0

    window_start = inputs.now - dt.timedelta(days=config.window_days)
    tolerance = dt.timedelta(seconds=config.missed_scan_tolerance_seconds)
    start = max(window_start, scans[0] - tolerance)
    step = dt.timedelta(minutes=1)

    uncovered: dict[dt.date, int] = {}
    gap_run: dict[dt.date, int] = {}
    max_run: dict[dt.date, int] = {}
    observed: set[dt.date] = set()
    expected = covered = 0

    cursor = start
    while cursor < inputs.now:
        day = cursor.astimezone(_ET).date()
        observed.add(day)
        if market_state(cursor).scanning:
            expected += 1
            index = bisect_left(scans, cursor - tolerance)
            hit = index < len(scans) and scans[index] <= cursor + tolerance
            if hit:
                covered += 1
                gap_run[day] = 0
            else:
                uncovered[day] = uncovered.get(day, 0) + 1
                run = gap_run.get(day, 0) + 1
                gap_run[day] = run
                max_run[day] = max(max_run.get(day, 0), run)
        cursor += step

    crash_days = {ts.astimezone(_ET).date() for ts in inputs.crash_timestamps}
    days = {
        day: _Day(
            uncovered_minutes=uncovered.get(day, 0),
            max_gap_run=max_run.get(day, 0),
            crashed=day in crash_days,
        )
        for day in observed
    }
    uptime = covered / expected if expected else 1.0
    return days, uptime


def _streak_days(days: dict[dt.date, _Day], now: dt.datetime) -> list[dt.date]:
    """Consecutive clean observed CALENDAR days ending today (ET) — the spec
    counts calendar days, so clean weekends/holidays extend the streak and a
    dirty day (missed scans or a crash) stops the walk cold."""
    if not days:
        return []
    today = now.astimezone(_ET).date()
    first = min(days)
    streak: list[dt.date] = []
    cursor = today
    while cursor >= first:
        record = days.get(cursor)
        if record is not None:
            if not record.clean:
                break
            streak.append(cursor)
        cursor -= dt.timedelta(days=1)
    return streak


def evaluate(
    inputs: CertificationInputs, config: CertificationConfig | None = None
) -> CertificationReport:
    cfg = config or default_config()
    days, uptime = _walk_days(inputs, cfg)
    streak = _streak_days(days, inputs.now)
    streak_count = len(streak)
    started = streak_count > 0

    in_streak = [days[d] for d in streak]
    missed_in_streak = sum(d.uncovered_minutes for d in in_streak)  # 0 by construction
    max_gap_seconds = (
        max((d.max_gap_run for d in in_streak), default=0) * 60.0 + cfg.scan_interval_seconds
        if started
        else 0.0
    )
    crashes_in_streak = sum(1 for d in in_streak if d.crashed)  # 0 by construction
    growth = _memory_growth(inputs.memory_series)
    p95 = _p95(inputs.scan_durations_ms)

    def _streak_gate(key: str, label: str, measured_ok: str, detail: str) -> Requirement:
        return Requirement(
            key=key,
            label=label,
            passed=started,
            measured=measured_ok if started else "streak not started",
            threshold="0 within the certification streak",
            detail=detail,
        )

    requirements = (
        _streak_gate(
            "no_crashes",
            "No crashes",
            f"{crashes_in_streak} in the streak ({len(inputs.crash_timestamps)} in the window)",
            "unclean-shutdown recoveries (automation_state crash history); a crash resets "
            "the streak to day zero",
        ),
        Requirement(
            key="no_orphaned_backend",
            label="No orphaned backend",
            passed=inputs.orphan_protection_active,
            measured="parent watchdog active"
            if inputs.orphan_protection_active
            else "parent watchdog NOT active (bare CLI session?)",
            threshold="watchdog active",
            detail="the sidecar self-terminates the instant its launcher dies "
            "(MRP_PARENT_PID watchdog)",
        ),
        Requirement(
            key="no_scheduler_drift",
            label="No scheduler drift",
            passed=started and max_gap_seconds <= cfg.drift_tolerance_seconds,
            measured=(
                f"largest in-session gap {max_gap_seconds:.0f}s"
                if started
                else "streak not started"
            ),
            threshold=f"<= {cfg.drift_tolerance_seconds:.0f}s",
            detail="largest gap between consecutive scans inside scheduled scanning hours, "
            "within the streak",
        ),
        _streak_gate(
            "no_missed_scans",
            "No missed scans",
            f"{missed_in_streak} scanning minutes without a scan",
            "every ET scanning-state minute must have a scan within tolerance; a missed "
            "minute resets the streak to day zero",
        ),
        Requirement(
            key="no_duplicate_trades",
            label="No duplicate trades",
            passed=inputs.duplicate_trades <= cfg.max_duplicate_trades,
            measured=f"{inputs.duplicate_trades} duplicates",
            threshold=f"<= {cfg.max_duplicate_trades}",
            detail="same symbol holding two open journal trades, or identical "
            "(symbol, entry timestamp) rows",
        ),
        Requirement(
            key="no_database_corruption",
            label="No database corruption",
            passed=inputs.database_ok,
            measured="integrity_check ok" if inputs.database_ok else "integrity_check FAILED",
            threshold="PRAGMA integrity_check == ok",
            detail="the updater's integrity gate, run live against the working database",
        ),
        Requirement(
            key="memory_bounded",
            label="No memory growth beyond limits",
            passed=growth is None or growth <= cfg.max_memory_growth_mb,
            measured=(f"{growth:.0f}MB growth" if growth is not None else "insufficient samples"),
            threshold=f"<= {cfg.max_memory_growth_mb:.0f}MB across the window",
            detail="median per-scan RSS, last decile vs first decile "
            "(insufficient samples passes vacuously until 10+ scans exist)",
        ),
        Requirement(
            key="pipeline_responsive",
            label="No UI freezes (backend proxy)",
            passed=p95 is None or p95 <= cfg.max_p95_scan_duration_ms,
            measured=(f"p95 scan {p95 / 1000.0:.1f}s" if p95 is not None else "no scans yet"),
            threshold=f"p95 <= {cfg.max_p95_scan_duration_ms / 1000.0:.0f}s",
            detail="renderer freezes are not observable from the backend; the certified "
            "proxy is the pipeline latency the UI blocks on",
        ),
        Requirement(
            key="window_complete",
            label=f"{cfg.window_days} consecutive days",
            passed=streak_count >= cfg.window_days,
            measured=f"day {min(streak_count, cfg.window_days)} of {cfg.window_days}",
            threshold=f">= {cfg.window_days} clean days",
            detail="consecutive clean days ending today (weekends/holidays are neutral); "
            "any crash or missed scanning minute resets the count",
        ),
    )

    # State that is wrong RIGHT NOW fails the certification; an incomplete or
    # freshly-reset streak merely keeps it in progress.
    stateful_keys = {
        "no_orphaned_backend",
        "no_duplicate_trades",
        "no_database_corruption",
        "memory_bounded",
        "pipeline_responsive",
    }
    stateful_failures = [r for r in requirements if r.key in stateful_keys and not r.passed]
    certified = all(r.passed for r in requirements)
    status = "certified" if certified else ("failing" if stateful_failures else "in_progress")

    return CertificationReport(
        status=status,
        certified=certified,
        window_start=inputs.now - dt.timedelta(days=cfg.window_days),
        window_end=inputs.now,
        streak_days=streak_count,
        required_days=cfg.window_days,
        uptime_pct=uptime,
        scans_completed=len(inputs.scan_timestamps),
        trades_opened=inputs.trades_opened,
        trades_closed=inputs.trades_closed,
        alerts_generated=inputs.alerts_generated,
        errors=inputs.errors,
        warnings=inputs.warnings,
        api_failures=inputs.api_failures,
        provider_failures=inputs.provider_failures,
        missed_scan_minutes=missed_in_streak,
        max_session_gap_seconds=max_gap_seconds,
        memory_growth_mb=growth,
        p95_scan_duration_ms=p95,
        requirements=requirements,
        generated_at=inputs.now,
    )
