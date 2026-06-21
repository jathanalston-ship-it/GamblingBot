"""Run the API as a local desktop sidecar.

    python -m momentum.api      # binds 127.0.0.1:8000 by default

Electron spawns this (or a PyInstaller-frozen equivalent) on startup and waits
for ``/health`` before showing the window. Host/port/DB come from the
environment (``MRP_API_HOST``, ``MRP_API_PORT``, ``DATABASE_URL``). The backend
is intentionally bound to loopback only — it is a private sidecar, never exposed.
"""

from __future__ import annotations

import os

import uvicorn

from momentum.api.app import create_app
from momentum.api.parent_watchdog import start_parent_watchdog
from momentum.api.user_settings import load_user_env
from momentum.core.logging import setup_logging
from momentum.persistence.database import (
    create_db_engine,
    create_session_factory,
    reconcile_schema,
)


def main() -> None:
    host = os.environ.get("MRP_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MRP_API_PORT", "8000"))

    # Write a real log file to MRP_LOG_DIR (the desktop sets this under the app's
    # userData/logs) so packaged-app failures are diagnosable instead of vanishing
    # to a stdout no one sees.
    log = setup_logging(log_dir=os.environ.get("MRP_LOG_DIR"))
    log.info("MRP backend starting: host=%s port=%s", host, port)

    # Self-terminate if the desktop launcher dies without cleaning us up (crash /
    # force-kill / system shutdown) so the sidecar can never be orphaned.
    if start_parent_watchdog() is not None:
        log.info("parent watchdog active (MRP_PARENT_PID=%s)", os.environ.get("MRP_PARENT_PID"))

    # Load any persisted provider API keys (.env under MRP_USER_DIR) before the
    # provider is built, so a configured Alpaca/Polygon key authenticates.
    load_user_env()

    try:
        engine = create_db_engine()
        log.info("database: %s", engine.url)
        # Create the schema on first launch AND self-heal an older database after an
        # app upgrade (add any new tables/columns) so reads never hit "no such column".
        reconcile_schema(engine)
        app = create_app(create_session_factory(engine))
    except Exception:
        log.exception("backend failed during startup")
        raise

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
