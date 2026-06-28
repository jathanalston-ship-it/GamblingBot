"""Trading-session-aware freshness for scans (``actions._evaluate_staleness``).

The bug this fixes: daily bars are routinely a few *calendar* days old over a
weekend/holiday, yet still the latest available session — they must read as FRESH.
Only data that is genuinely several trading sessions behind is stale.
"""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.api import actions


def _utc(y: int, m: int, d: int, hh: int = 21, mm: int = 0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=dt.UTC)


# A clean week with no holidays: 2026-06-05 Fri, 06-08 Mon ... 06-12 Fri.
# (NB: 2026-06-19 is Juneteenth — deliberately avoided.)
def test_friday_bar_pulled_monday_is_fresh() -> None:
    bar = _utc(2026, 6, 5, 20)  # Friday's session close
    pull = _utc(2026, 6, 8, 13)  # Monday mid-session
    age, stale, reason = actions._evaluate_staleness(bar, pull)
    assert stale is False
    assert "1 trading session" in reason
    assert age is not None and age > 60 * 24  # ~2.7 calendar days, but still fresh


def test_yesterday_bar_pulled_today_preclose_is_fresh() -> None:
    bar = _utc(2026, 6, 11, 20)  # Thursday close
    pull = _utc(2026, 6, 12, 14)  # Friday, before today's bar exists
    _age, stale, _reason = actions._evaluate_staleness(bar, pull)
    assert stale is False


def test_five_sessions_old_is_stale() -> None:
    bar = _utc(2026, 6, 5, 20)  # Friday
    pull = _utc(2026, 6, 12, 14)  # next Friday — 5 sessions later
    _age, stale, reason = actions._evaluate_staleness(bar, pull)
    assert stale is True
    assert "session" in reason


def test_no_bars_is_stale() -> None:
    age, stale, reason = actions._evaluate_staleness(None, _utc(2026, 6, 12))
    assert stale is True and age is None
    assert "no market data" in reason


def test_explicit_minute_threshold_overrides_session_rule() -> None:
    bar = _utc(2026, 6, 5, 20)  # Friday
    pull = _utc(2026, 6, 8, 13)  # Monday — fresh by sessions...
    # ...but an explicit tight minute threshold (intraday) flags it stale.
    _age, stale, _reason = actions._evaluate_staleness(bar, pull, stale_after_minutes=60)
    assert stale is True


def test_env_minute_threshold_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRP_STALE_AFTER_MINUTES", "60")
    bar = _utc(2026, 6, 5, 20)
    pull = _utc(2026, 6, 8, 13)
    _age, stale, _reason = actions._evaluate_staleness(bar, pull)
    assert stale is True


def test_max_stale_sessions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRP_MAX_STALE_SESSIONS", "0")
    bar = _utc(2026, 6, 5, 20)  # Friday
    pull = _utc(2026, 6, 8, 13)  # Monday — 1 session behind
    _age, stale, _reason = actions._evaluate_staleness(bar, pull)
    assert stale is True  # tolerance of 0 sessions → even 1 behind is stale


def test_sessions_behind_skips_weekend() -> None:
    # Friday -> Monday is one session, not three calendar days.
    assert actions._sessions_behind(_utc(2026, 6, 5), _utc(2026, 6, 8)) == 1
    # Same-session pull is zero behind.
    assert actions._sessions_behind(_utc(2026, 6, 8), _utc(2026, 6, 8)) == 0
