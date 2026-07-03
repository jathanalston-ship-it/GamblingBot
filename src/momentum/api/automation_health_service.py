"""Long-Running Trading Mode — the preflight every autopilot start must pass.

Seven subsystems are graded ``healthy`` / ``warning`` / ``critical`` with a
measured detail each; the overall grade is the worst subsystem. Enabling
autopilot (``PUT /settings/autopilot`` with ``enabled=true``) runs this
preflight and **refuses to start** when anything backend-checkable is
critical, returning every failing subsystem and why. The Command Center's
Automation panel shows the live grades continuously.

Subsystems:

* **backend** — this process answered; trivially healthy.
* **scheduler** — the market daemon thread exists and is running.
* **sleep_prevention** — owned by the Electron shell (powerSaveBlocker); the
  backend cannot observe it, so it reports the *setting* and the shell
  merges the live blocker state into the UI.
* **internet** — a real HTTPS probe (3s timeout) against the data provider's
  host.
* **market_calendar** — the trading calendar resolves today/next session.
* **clock_sync** — local UTC vs the probe response's ``Date`` header;
  drift > 2 min is warning, > 10 min critical (a drifted clock corrupts the
  schedule).
* **data_provider** — the probe reached the configured provider's endpoint.

The network probe is injectable/monkeypatchable so tests run offline.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

_log = logging.getLogger(__name__)

_ORDER = {"healthy": 0, "warning": 1, "critical": 2}

CLOCK_WARNING_SECONDS = 120.0
CLOCK_CRITICAL_SECONDS = 600.0

_PROVIDER_PROBE_URLS = {
    "yfinance": "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=1d&interval=1d",
    "alpaca": "https://data.alpaca.markets/v2/stocks/SPY/bars/latest",
    "polygon": "https://api.polygon.io/v1/marketstatus/now",
}


@dataclass(frozen=True, slots=True)
class SubsystemHealth:
    name: str
    status: str  # healthy | warning | critical
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _probe(url: str) -> tuple[int | None, str | None, float]:
    """(status_code, Date header, elapsed_ms); (None, None, ms) on failure."""
    started = time.perf_counter()
    try:
        response = httpx.get(url, timeout=3.0, follow_redirects=True)
        elapsed = (time.perf_counter() - started) * 1000.0
        return response.status_code, response.headers.get("date"), elapsed
    except Exception:  # noqa: BLE001 — any transport failure = unreachable
        return None, None, (time.perf_counter() - started) * 1000.0


def check_all(*, daemon: Any | None = None) -> dict[str, Any]:
    """Grade every subsystem; overall = the worst one."""
    from momentum.api import user_settings

    checks: list[SubsystemHealth] = [SubsystemHealth("backend", "healthy", "API process answering")]

    # Scheduler (the market daemon).
    if daemon is None:
        checks.append(
            SubsystemHealth(
                "scheduler",
                "warning",
                "market daemon not attached to this process (desktop app starts it; "
                "bare API sessions scan manually)",
            )
        )
    else:
        status = daemon.status() if hasattr(daemon, "status") else {}
        running = bool(status.get("running"))
        paused = bool(status.get("paused"))
        if running and not paused:
            checks.append(SubsystemHealth("scheduler", "healthy", "daemon thread running"))
        elif running and paused:
            checks.append(SubsystemHealth("scheduler", "warning", "daemon is paused — resume it"))
        else:
            checks.append(SubsystemHealth("scheduler", "critical", "daemon thread not running"))

    # Sleep prevention: the setting is backend-owned; the live blocker is the
    # shell's (merged in the UI). A disabled setting is an informed choice.
    prevent = bool(user_settings.read_autopilot().get("prevent_sleep", True))
    checks.append(
        SubsystemHealth(
            "sleep_prevention",
            "healthy" if prevent else "warning",
            "prevent-sleep enabled (the desktop shell holds a power-save blocker "
            "while Auto Pilot runs)"
            if prevent
            else "prevent-sleep disabled — the OS may sleep and pause automation",
        )
    )

    # Internet + provider + clock, from one real probe.
    provider = user_settings.read_provider()
    url = _PROVIDER_PROBE_URLS.get(provider, _PROVIDER_PROBE_URLS["yfinance"])
    status_code, date_header, elapsed_ms = _probe(url)
    if status_code is None:
        checks.append(
            SubsystemHealth("internet", "critical", f"cannot reach {url.split('/')[2]} within 3s")
        )
        checks.append(
            SubsystemHealth(
                "data_provider", "critical", f"provider '{provider}' unreachable — no market data"
            )
        )
        checks.append(
            SubsystemHealth("clock_sync", "warning", "cannot verify clock drift while offline")
        )
    else:
        checks.append(
            SubsystemHealth(
                "internet", "healthy", f"reached {url.split('/')[2]} in {elapsed_ms:.0f}ms"
            )
        )
        # Auth failures still prove reachability; 5xx means the vendor is down.
        if status_code < 500:
            detail = f"provider '{provider}' answered HTTP {status_code}"
            checks.append(SubsystemHealth("data_provider", "healthy", detail))
        else:
            checks.append(
                SubsystemHealth(
                    "data_provider",
                    "critical",
                    f"provider '{provider}' returned HTTP {status_code}",
                )
            )
        checks.append(_clock_check(date_header))

    checks.append(_calendar_check())

    overall = max((c.status for c in checks), key=lambda s: _ORDER[s])
    return {
        "overall": overall,
        "checks": [c.to_dict() for c in checks],
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
    }


def _clock_check(date_header: str | None) -> SubsystemHealth:
    if not date_header:
        return SubsystemHealth("clock_sync", "warning", "no Date header to compare against")
    try:
        from email.utils import parsedate_to_datetime

        remote = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return SubsystemHealth("clock_sync", "warning", "unparseable Date header")
    drift = abs((dt.datetime.now(tz=dt.UTC) - remote).total_seconds())
    if drift > CLOCK_CRITICAL_SECONDS:
        return SubsystemHealth(
            "clock_sync",
            "critical",
            f"system clock is {drift:.0f}s off — the ET schedule cannot be trusted",
        )
    if drift > CLOCK_WARNING_SECONDS:
        return SubsystemHealth("clock_sync", "warning", f"system clock is {drift:.0f}s off")
    return SubsystemHealth("clock_sync", "healthy", f"clock within {drift:.0f}s of the provider")


def _calendar_check() -> SubsystemHealth:
    try:
        from momentum.daemon.market_state import market_clock

        clock = market_clock(dt.datetime.now(tz=dt.UTC))
        return SubsystemHealth(
            "market_calendar",
            "healthy",
            f"schedule loaded — market is '{clock.state.value}'",
        )
    except Exception as exc:  # noqa: BLE001 — a broken calendar is critical
        return SubsystemHealth("market_calendar", "critical", f"calendar failed: {exc}")


def preflight_failures(*, daemon: Any | None = None) -> list[dict[str, Any]]:
    """The critical subsystems blocking an autopilot start ([] = clear)."""
    report = check_all(daemon=daemon)
    return [c for c in report["checks"] if c["status"] == "critical"]
