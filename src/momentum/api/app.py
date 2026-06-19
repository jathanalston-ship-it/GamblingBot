"""FastAPI application factory.

``create_app`` wires the read-only routers and stores a SQLAlchemy session
factory on ``app.state``. Tests pass their own (in-memory) factory; in
production the factory is built from ``DATABASE_URL`` via the persistence layer.

Run locally::

    uvicorn momentum.api.app:create_app --factory --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from momentum.api.routes import (
    backtests,
    health,
    performance,
    portfolio,
    regimes,
    risk,
    signals,
    trades,
    universe,
)
from momentum.persistence.database import create_db_engine, create_session_factory

_ROUTERS = (
    health,
    signals,
    trades,
    regimes,
    portfolio,
    risk,
    universe,
    backtests,
    performance,
)


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    """Build the FastAPI app. Inject ``session_factory`` for tests."""
    app = FastAPI(
        title="Momentum Research Platform API",
        version="0.1.0",
        description=(
            "Read-only API over the MRP research database: signals, trades, "
            "regimes, portfolio snapshots, risk metrics, scans, optimizations "
            "and performance summaries."
        ),
    )

    if session_factory is None:
        session_factory = create_session_factory(create_db_engine())
    app.state.session_factory = session_factory

    for module in _ROUTERS:
        app.include_router(module.router)

    return app
