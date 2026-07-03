"""Automation resilience — persisted heartbeat, crash detection, recovery.

A tiny JSON file in the writable user dir (``automation_state.json``) makes
long-running automation survivable:

* the daemon **heartbeats** into it every cycle (and every closed-market
  state check), stamping the freshest scan time;
* a **clean shutdown** marks the file, so a normal quit is never mistaken
  for a crash;
* on startup, :func:`detect_recovery` compares the last heartbeat with now —
  a stale, unclean heartbeat means the process died (crash / power loss /
  OS restart). The downtime and the number of scans the daemon *would have
  run* while the market was open (:func:`missed_scans_between`, sampled
  against the real ET schedule) are recorded and surfaced at
  ``GET /automation/recovery`` so the Command Center can show
  "Recovered after restart — missed N scans — resuming".

Resuming itself is inherent to the architecture: autopilot lives in
``settings.yaml``, positions in the ``trades`` table, and the daemon
autostarts with the app — nothing here re-creates state, it only *measures
and reports* the gap.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

STATE_FILE = "automation_state.json"

# A heartbeat older than this at startup means the previous process died
# without a clean shutdown (the daemon beats every cycle, 60s-900s apart).
STALE_AFTER_SECONDS = 30 * 60


def _state_path() -> Path:
    from momentum.api.user_settings import _user_dir

    return _user_dir() / STATE_FILE


def _read() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict[str, Any]) -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a power loss mid-write must never leave a torn file
        # (a torn heartbeat would otherwise be unreadable after the restart —
        # exactly when the recovery record matters most).
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)
    except OSError:  # a failed heartbeat must never break a scan cycle
        _log.debug("automation state write failed", exc_info=True)


def record_heartbeat(
    *, ts: dt.datetime, last_scan: dt.datetime | None = None, interval_seconds: float = 60.0
) -> None:
    """The daemon is alive right now (called every cycle / state check)."""
    data = _read()
    data["last_heartbeat"] = ts.isoformat()
    data["clean_shutdown"] = False
    data["scan_interval_seconds"] = interval_seconds
    if last_scan is not None:
        data["last_scan"] = last_scan.isoformat()
    _write(data)


def mark_clean_shutdown(*, ts: dt.datetime | None = None) -> None:
    """A deliberate stop — the next startup must not report a crash."""
    data = _read()
    data["clean_shutdown"] = True
    data["shutdown_at"] = (ts or dt.datetime.now(tz=dt.UTC)).isoformat()
    _write(data)


def missed_scans_between(
    start: dt.datetime, end: dt.datetime, *, interval_seconds: float = 60.0
) -> int:
    """How many scans the daemon would have run in the window.

    Sampled minute-by-minute against the real ET schedule: only minutes in a
    *scanning* market state (premarket / regular / after-hours) count, so an
    overnight or weekend outage honestly reports zero missed scans.
    """
    from momentum.daemon.market_state import market_state

    if end <= start or interval_seconds <= 0:
        return 0
    scanning_seconds = 0.0
    cursor = start
    step = dt.timedelta(minutes=1)
    # Cap the walk at 14 days — beyond that the count saturates anyway.
    horizon = min(end, start + dt.timedelta(days=14))
    while cursor < horizon:
        if market_state(cursor).scanning:
            scanning_seconds += min(step.total_seconds(), (horizon - cursor).total_seconds())
        cursor += step
    return int(scanning_seconds // interval_seconds)


def detect_recovery(*, now: dt.datetime | None = None) -> dict[str, Any] | None:
    """At startup: did the previous run die uncleanly? Record + return the gap.

    Returns ``None`` for a first run, a clean prior shutdown, or a fresh
    heartbeat (a fast dev restart is not a crash). Otherwise persists and
    returns a recovery record; the record stays until the next crash so the
    UI can keep showing it.
    """
    when = now or dt.datetime.now(tz=dt.UTC)
    data = _read()
    raw = data.get("last_heartbeat")
    if not raw or data.get("clean_shutdown") is True:
        return None
    try:
        last = dt.datetime.fromisoformat(str(raw))
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.UTC)
    except ValueError:
        return None
    downtime = (when - last).total_seconds()
    if downtime < STALE_AFTER_SECONDS:
        return None

    interval = float(data.get("scan_interval_seconds") or 60.0)
    missed = missed_scans_between(last, when, interval_seconds=interval)
    recovery = {
        "recovered_at": when.isoformat(),
        "went_down_at": last.isoformat(),
        "downtime_seconds": round(downtime, 1),
        "missed_scans": missed,
    }
    data["last_recovery"] = recovery
    data["last_heartbeat"] = when.isoformat()  # don't re-report the same gap
    _write(data)
    _log.warning(
        "recovered after unclean shutdown: down %.0f min, %d scans missed",
        downtime / 60.0,
        missed,
    )
    return recovery


def last_recovery() -> dict[str, Any] | None:
    """The most recent recovery record (None when there has never been one)."""
    record = _read().get("last_recovery")
    return dict(record) if isinstance(record, dict) else None


def snapshot() -> dict[str, Any]:
    """The raw persisted state (diagnostics)."""
    return _read()
