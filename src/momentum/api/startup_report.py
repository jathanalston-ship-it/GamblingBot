"""Backend-side startup diagnostic report.

The desktop launcher (Electron) owns the authoritative startup report — it alone
knows the spawn → health duration and the final health status. But the backend
knows things the launcher cannot see from the outside: which executable is
actually running, its PID, the configuration it loaded, the database it opened
and any exception raised before it could serve. This module records exactly that
to a small JSON file under the log directory so a failed launch is diagnosable
from disk without a terminal.

Pure builder (`build_startup_report`) + a crash-safe writer (`write_startup_report`).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_FILENAME = "backend-startup.json"


def build_startup_report(
    *,
    host: str,
    port: int,
    pid: int,
    executable: str,
    argv: list[str],
    db_url: str | None,
    log_dir: str | None,
    user_dir: str | None,
    parent_pid: str | None,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    """Assemble the backend's view of its own startup as a JSON-able dict."""
    return {
        "ts": datetime.now(UTC).isoformat(),
        "pid": pid,
        "executable": executable,
        "argv": list(argv),
        "frozen": bool(getattr(sys, "frozen", False)),
        "status": status,  # "starting" | "serving" | "failed"
        "configuration": {
            "host": host,
            "port": port,
            "log_dir": log_dir,
            "user_dir": user_dir,
            "parent_pid": parent_pid,
        },
        "database_url": db_url,
        "error": error,
    }


def write_startup_report(log_dir: str | None, report: dict[str, Any]) -> str | None:
    """Write *report* to ``<log_dir>/backend-startup.json``; return the path.

    Best-effort and never raises — a diagnostic must not be able to break startup.
    Falls back silently if no log dir is configured or the write fails.
    """
    if not log_dir:
        return None
    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        target = path / REPORT_FILENAME
        with target.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        return str(target)
    except OSError:
        return None
