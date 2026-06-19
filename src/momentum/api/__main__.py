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
from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
)


def main() -> None:
    host = os.environ.get("MRP_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MRP_API_PORT", "8000"))

    engine = create_db_engine()
    create_all(engine)  # ensure the SQLite schema exists on first launch
    app = create_app(create_session_factory(engine))

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
