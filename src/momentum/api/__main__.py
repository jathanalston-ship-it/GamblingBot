"""Run the API as a local desktop sidecar.

    python -m momentum.api      # binds 127.0.0.1:8000 by default

Electron spawns this (or a PyInstaller-frozen equivalent) on startup and waits
for ``/health`` before showing the window. Host/port/DB come from the
environment (``MRP_API_HOST``, ``MRP_API_PORT``, ``DATABASE_URL``). The backend
is intentionally bound to loopback only — it is a private sidecar, never exposed.
"""

from __future__ import annotations

import os
import sys

import uvicorn

from momentum.api.app import create_app
from momentum.api.parent_watchdog import start_parent_watchdog
from momentum.api.startup_report import build_startup_report, write_startup_report
from momentum.api.user_settings import load_user_env, read_provider
from momentum.core import secrets
from momentum.core.logging import setup_logging
from momentum.persistence.database import (
    create_db_engine,
    create_session_factory,
    reconcile_schema,
)


def main() -> None:
    host = os.environ.get("MRP_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MRP_API_PORT", "8000"))
    log_dir = os.environ.get("MRP_LOG_DIR")

    # Write a real log file to MRP_LOG_DIR (the desktop sets this under the app's
    # userData/logs) so packaged-app failures are diagnosable instead of vanishing
    # to a stdout no one sees.
    log = setup_logging(log_dir=log_dir)
    log.info("MRP backend starting: host=%s port=%s pid=%s", host, port, os.getpid())

    def diagnostic(status: str, db_url: str | None, error: str | None = None) -> None:
        """Record the backend's view of its own startup to disk (best-effort)."""
        report = build_startup_report(
            host=host,
            port=port,
            pid=os.getpid(),
            executable=sys.executable,
            argv=sys.argv,
            db_url=db_url,
            log_dir=log_dir,
            user_dir=os.environ.get("MRP_USER_DIR"),
            parent_pid=os.environ.get("MRP_PARENT_PID"),
            status=status,
            error=error,
        )
        path = write_startup_report(log_dir, report)
        if path is not None:
            log.info("startup diagnostic written: %s (status=%s)", path, status)

    # Self-terminate if the desktop launcher dies without cleaning us up (crash /
    # force-kill / system shutdown) so the sidecar can never be orphaned.
    if start_parent_watchdog() is not None:
        log.info("parent watchdog active (MRP_PARENT_PID=%s)", os.environ.get("MRP_PARENT_PID"))

    # Load any persisted provider API keys (.env under MRP_USER_DIR) before the
    # provider is built, so a configured Alpaca/Polygon key authenticates.
    load_user_env()

    # Validate that the secrets required by the ACTIVE configuration are present.
    # The message is value-free (never logs a secret). This is non-fatal so the
    # desktop app still boots to Settings where keys can be entered — unless
    # MRP_STRICT_SECRETS=1 (operator/CI), which makes a missing secret a hard error.
    provider = read_provider()
    environment = os.environ.get("MRP_ENV", "research")
    report = secrets.validate(provider=provider, environment=environment)
    if report.ok:
        log.info("secret validation: %s", report.message())
    else:
        log.error("secret validation: %s", report.message())
        if os.environ.get("MRP_STRICT_SECRETS") == "1":
            diagnostic("failed", None, error=report.message())
            raise secrets.MissingSecretsError(report)

    db_url: str | None = None
    try:
        engine = create_db_engine()
        db_url = str(engine.url)
        log.info("database: %s", db_url)
        # Create the schema on first launch AND self-heal an older database after an
        # app upgrade (add any new tables/columns) so reads never hit "no such column".
        reconcile_schema(engine)
        app = create_app(create_session_factory(engine))
    except Exception as exc:
        log.exception("backend failed during startup")
        diagnostic("failed", db_url, error=f"{type(exc).__name__}: {exc}")
        raise

    # Configuration loaded, DB opened, app built — record success before we hand off
    # to uvicorn (which blocks serving requests).
    diagnostic("serving", db_url)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
