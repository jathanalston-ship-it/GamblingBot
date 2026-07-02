"""Market-daemon endpoints: status, events, pause/resume, manual scan.

The daemon lives on ``app.state.market_daemon`` (created at startup when
enabled). Controls return the fresh status so the UI reflects the change
immediately; ``scan-now`` doubles as both "manual scan" and "immediate
refresh" — it interrupts any sleep and runs a full cycle regardless of the
market schedule.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from momentum.api.schemas import ClockOut, DaemonEventOut, DaemonStatusOut

router = APIRouter(prefix="/daemon", tags=["daemon"])


def _daemon(request: Request) -> Any:
    daemon = getattr(request.app.state, "market_daemon", None)
    if daemon is None:
        raise HTTPException(
            status_code=409,
            detail="market daemon is not enabled (set MRP_DAEMON_AUTOSTART=1 or start it)",
        )
    return daemon


def _disabled_status() -> DaemonStatusOut:
    """An honest 'not running' status when the daemon was never created."""
    import datetime as dt

    from momentum.daemon import market_state

    return DaemonStatusOut(
        running=False,
        paused=False,
        scanning_now=False,
        market_state=market_state(dt.datetime.now(tz=dt.UTC)).value,
        scan_interval_seconds=0.0,
        closed_interval_seconds=0.0,
        cycles=0,
        failures=0,
        consecutive_failures=0,
        last_scan_at=None,
        last_error="daemon disabled (MRP_DAEMON_AUTOSTART is not set)",
        next_wake_at=None,
        seconds_to_next_wake=None,
        version=0,
        last_result=None,
        cached_symbols=0,
    )


def _status(request: Request) -> DaemonStatusOut:
    daemon = getattr(request.app.state, "market_daemon", None)
    if daemon is None:
        return _disabled_status()
    cache = getattr(request.app.state, "daemon_cache", None)
    payload = daemon.status()
    payload["cached_symbols"] = cache.size() if cache is not None else 0
    return DaemonStatusOut(**payload)


@router.get("/status", response_model=DaemonStatusOut)
def status(request: Request) -> DaemonStatusOut:
    """Live worker status (state, schedule, last/next scan, failures, version)."""
    return _status(request)


@router.get("/events", response_model=list[DaemonEventOut])
def events(request: Request, limit: int = 50) -> list[DaemonEventOut]:
    """The daemon's recent published events, newest first ([] when disabled)."""
    daemon = getattr(request.app.state, "market_daemon", None)
    if daemon is None:
        return []
    return [DaemonEventOut(**e) for e in daemon.events(limit)]


@router.post("/pause", response_model=DaemonStatusOut)
def pause(request: Request) -> DaemonStatusOut:
    _daemon(request).pause()
    return _status(request)


@router.post("/resume", response_model=DaemonStatusOut)
def resume(request: Request) -> DaemonStatusOut:
    _daemon(request).resume()
    return _status(request)


@router.post("/scan-now", response_model=DaemonStatusOut)
def scan_now(request: Request) -> DaemonStatusOut:
    """Manual scan / immediate refresh: run a full cycle as soon as possible."""
    _daemon(request).trigger_scan()
    return _status(request)


@router.get("/clock", response_model=ClockOut)
def clock(request: Request) -> ClockOut:
    """Market time/status + countdowns for the live clock widget.

    All values are unambiguous (ISO with offsets, seconds). The *local* clock is
    rendered client-side — only the client knows the operating system's zone.
    """
    import datetime as dt

    from momentum.daemon import market_clock

    payload = market_clock(dt.datetime.now(tz=dt.UTC)).to_dict()
    daemon = getattr(request.app.state, "market_daemon", None)
    seconds_to_next_scan = None
    running = False
    if daemon is not None:
        status_payload = daemon.status()
        running = bool(status_payload.get("running"))
        seconds_to_next_scan = status_payload.get("seconds_to_next_wake")
    return ClockOut(
        **payload,
        seconds_to_next_scan=seconds_to_next_scan,
        daemon_running=running,
    )
