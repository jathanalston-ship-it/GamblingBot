"""Certification engine tests — pure grading over synthetic operation."""

from __future__ import annotations

import datetime as dt

from momentum.certification import CertificationConfig, CertificationInputs, evaluate
from momentum.daemon.market_state import market_state

NOW = dt.datetime(2026, 7, 1, 18, 0, tzinfo=dt.UTC)  # Wednesday 14:00 ET (open)

FAST = CertificationConfig(window_days=5)


def _scans_between(
    start: dt.datetime, end: dt.datetime, *, step_seconds: float = 60.0
) -> tuple[dt.datetime, ...]:
    """A perfect daemon: one scan per scanning-state minute."""
    out: list[dt.datetime] = []
    cursor = start
    step = dt.timedelta(seconds=step_seconds)
    while cursor < end:
        if market_state(cursor).scanning:
            out.append(cursor)
        cursor += step
    return tuple(out)


def _inputs(
    *,
    now: dt.datetime = NOW,
    days_running: float = 6.0,
    hole: tuple[dt.datetime, dt.datetime] | None = None,
    crash_timestamps: tuple[dt.datetime, ...] = (),
    duplicate_trades: int = 0,
    database_ok: bool = True,
    orphan_protection_active: bool = True,
    memory_series: tuple[float, ...] | None = None,
) -> CertificationInputs:
    scans = _scans_between(now - dt.timedelta(days=days_running), now)
    if hole is not None:
        scans = tuple(ts for ts in scans if not (hole[0] <= ts <= hole[1]))
    return CertificationInputs(
        now=now,
        scan_timestamps=scans,
        memory_series=memory_series if memory_series is not None else (400.0,) * 50,
        scan_durations_ms=(2_000.0,) * max(len(scans), 1),
        crash_timestamps=crash_timestamps,
        trades_opened=12,
        trades_closed=9,
        alerts_generated=30,
        errors=0,
        warnings=2,
        api_failures=0,
        provider_failures=1,
        duplicate_trades=duplicate_trades,
        database_ok=database_ok,
        orphan_protection_active=orphan_protection_active,
    )


def test_full_clean_window_certifies() -> None:
    report = evaluate(_inputs(), FAST)
    assert report.status == "certified"
    assert report.certified is True
    assert report.streak_days >= FAST.window_days
    assert report.missed_scan_minutes == 0
    assert report.uptime_pct == 1.0
    assert all(r.passed for r in report.requirements)


def test_partial_window_is_in_progress_never_certified() -> None:
    report = evaluate(_inputs(days_running=2.0), FAST)
    assert report.status == "in_progress"
    assert report.certified is False
    window = next(r for r in report.requirements if r.key == "window_complete")
    assert not window.passed
    assert "of 5" in window.measured
    # The streak gates themselves are healthy — only the calendar is short.
    assert next(r for r in report.requirements if r.key == "no_missed_scans").passed


def test_crash_resets_the_streak_to_that_day() -> None:
    crash = NOW - dt.timedelta(days=1)
    report = evaluate(_inputs(crash_timestamps=(crash,)), FAST)
    assert report.certified is False
    assert report.status == "in_progress"  # rebuilding, not permanently failing
    assert report.streak_days == 1  # only today survives


def test_missed_scans_break_that_day() -> None:
    hole_start = NOW - dt.timedelta(days=1, hours=2)
    report = evaluate(_inputs(hole=(hole_start, hole_start + dt.timedelta(hours=2))), FAST)
    assert report.certified is False
    assert report.streak_days == 1  # yesterday is dirty; today is clean
    assert report.uptime_pct < 1.0


def test_stateful_problems_fail_outright() -> None:
    report = evaluate(_inputs(duplicate_trades=2), FAST)
    assert report.status == "failing"
    assert not next(r for r in report.requirements if r.key == "no_duplicate_trades").passed

    corrupt = evaluate(_inputs(database_ok=False), FAST)
    assert corrupt.status == "failing"

    orphanable = evaluate(_inputs(orphan_protection_active=False), FAST)
    assert orphanable.status == "failing"


def test_memory_growth_beyond_limit_fails() -> None:
    rising = tuple(100.0 + i * 10.0 for i in range(60))  # +590MB across the window
    report = evaluate(_inputs(memory_series=rising), FAST)
    assert report.status == "failing"
    memory = next(r for r in report.requirements if r.key == "memory_bounded")
    assert not memory.passed
    assert report.memory_growth_mb is not None and report.memory_growth_mb > 300


def test_no_scans_yet_is_day_zero_in_progress() -> None:
    report = evaluate(
        CertificationInputs(
            now=NOW,
            scan_timestamps=(),
            memory_series=(),
            scan_durations_ms=(),
            crash_timestamps=(),
            trades_opened=0,
            trades_closed=0,
            alerts_generated=0,
            errors=0,
            warnings=0,
            api_failures=0,
            provider_failures=0,
            duplicate_trades=0,
            database_ok=True,
            orphan_protection_active=True,
        ),
        FAST,
    )
    assert report.status == "in_progress"
    assert report.streak_days == 0
    assert report.uptime_pct == 0.0
    assert report.scans_completed == 0


def test_clean_weekend_extends_the_calendar_streak() -> None:
    monday = dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)  # Monday 14:00 ET
    report = evaluate(_inputs(now=monday, days_running=4.0), FAST)
    # Thu/Fri clean trading days + Sat/Sun neutral-clean + Monday-so-far.
    assert report.streak_days >= 4
    assert next(r for r in report.requirements if r.key == "no_missed_scans").passed
