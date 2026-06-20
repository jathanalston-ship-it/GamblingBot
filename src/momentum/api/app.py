"""FastAPI application factory.

``create_app`` wires the read-only routers and stores a SQLAlchemy session
factory on ``app.state``. Tests pass their own (in-memory) factory; in
production the factory is built from ``DATABASE_URL`` via the persistence layer.

Run locally::

    uvicorn momentum.api.app:create_app --factory --reload
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from momentum.api.routes import (
    actions,
    analogs,
    audit,
    backtests,
    candidates,
    conviction,
    dashboard,
    health,
    opportunity,
    performance,
    portfolio,
    regimes,
    risk,
    runs,
    settings,
    signals,
    trades,
    universe,
    update,
)
from momentum.api.jobs import JobManager
from momentum.persistence.database import create_db_engine, create_session_factory

_ROUTERS = (
    health,
    dashboard,
    candidates,
    signals,
    trades,
    regimes,
    portfolio,
    risk,
    universe,
    conviction,
    opportunity,
    analogs,
    backtests,
    performance,
    settings,
    update,
    actions,
    runs,
    audit,
)


def _cors_origins() -> list[str]:
    """Allowed origins for the desktop renderer (Vite dev server / packaged app).

    The backend binds to ``127.0.0.1`` only (a local sidecar), so the default is
    permissive; override with ``MRP_CORS_ORIGINS`` (comma-separated) to lock down.
    """
    raw = os.environ.get("MRP_CORS_ORIGINS", "*")
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    """Build the FastAPI app. Inject ``session_factory`` for tests."""
    app = FastAPI(
        title="Momentum Research Platform API",
        version="0.1.0",
        description=(
            "Read-only API over the MRP research database: dashboard, signals, "
            "trades, regimes, portfolio snapshots, risk metrics, scans, "
            "optimizations, performance summaries and configuration."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if session_factory is None:
        session_factory = create_session_factory(create_db_engine())
    app.state.session_factory = session_factory
    # Background-job manager for operator-console actions (scan/backtest/paper/…).
    app.state.job_manager = JobManager()

    for module in _ROUTERS:
        app.include_router(module.router)

    return app
