"""FastAPI application factory.

``create_app`` wires the read-only routers and stores a SQLAlchemy session
factory on ``app.state``. Tests pass their own (in-memory) factory; in
production the factory is built from ``DATABASE_URL`` via the persistence layer.

Run locally::

    uvicorn momentum.api.app:create_app --factory --reload
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.orm import Session, sessionmaker

from momentum.api.routes import (
    actions,
    analogs,
    api_health,
    audit,
    backtests,
    candidates,
    command_center,
    conviction,
    dashboard,
    data_health,
    diagnostics,
    market_data,
    provenance,
    verification,
    health,
    opportunity,
    options_eligibility,
    options_recommendation,
    performance,
    portfolio,
    regimes,
    risk,
    runs,
    settings,
    signal_audit,
    signal_eval,
    signals,
    lifecycles,
    trades,
    tradeplan,
    universe,
    universes,
    update,
    watchlist_performance,
    watchlists,
)
from momentum.api.diagnostics import ErrorRecorder, build_record
from momentum.api.jobs import JobManager
from momentum.persistence.database import create_db_engine, create_session_factory

_log = logging.getLogger(__name__)

_ROUTERS = (
    health,
    api_health,
    dashboard,
    candidates,
    signals,
    trades,
    regimes,
    portfolio,
    risk,
    universe,
    universes,
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
    watchlists,
    tradeplan,
    lifecycles,
    command_center,
    signal_eval,
    options_eligibility,
    options_recommendation,
    watchlist_performance,
    signal_audit,
    data_health,
    provenance,
    market_data,
    verification,
    diagnostics,
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
    # Activate the persisted data mode (demo vs production). Importing the module
    # registers the global demo-exclusion query filter; loading sets the flag.
    from momentum.api import data_mode

    data_mode.load_from_settings()
    # Background-job manager for operator-console actions (scan/backtest/paper/…).
    app.state.job_manager = JobManager()
    # In-memory ring buffer of recent unhandled exceptions (Diagnostics screen).
    app.state.error_recorder = ErrorRecorder()

    for module in _ROUTERS:
        app.include_router(module.router)

    # Surface the real error on a 500 instead of an opaque "Internal Server Error".
    # The backend is a private loopback sidecar, so returning the exception type +
    # message is safe and makes failures diagnosable from the UI and the logs
    # (FastAPI's default handler hides the cause behind a bare 500).
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, StarletteHTTPException):  # 404/explicit HTTPException
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        # Capture into the diagnostics buffer (route, stack trace, params, timestamp)
        # so the failure is queryable via /diagnostics/recent-errors. Secret-redacted.
        record = build_record(request, exc)
        recorder: ErrorRecorder | None = getattr(app.state, "error_recorder", None)
        if recorder is not None:
            recorder.record(record)
        # Log the full context too (the RedactingFormatter scrubs any secret value).
        _log.exception(
            "unhandled %s on %s %s [route=%s] query=%s path_params=%s",
            record.exc_type,
            record.method,
            record.path,
            record.route,
            record.query_params,
            record.path_params,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}", "path": request.url.path},
        )

    return app
