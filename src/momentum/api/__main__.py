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
from momentum.api.user_settings import load_user_env
from momentum.persistence.database import (
    create_db_engine,
    create_session_factory,
    reconcile_schema,
)


def main() -> None:
    host = os.environ.get("MRP_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MRP_API_PORT", "8000"))

    # Load any persisted provider API keys (.env under MRP_USER_DIR) before the
    # provider is built, so a configured Alpaca/Polygon key authenticates.
    load_user_env()

    engine = create_db_engine()
    # Create the schema on first launch AND self-heal an older database after an
    # app upgrade (add any new tables/columns) so reads never hit "no such column".
    reconcile_schema(engine)
    app = create_app(create_session_factory(engine))

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
