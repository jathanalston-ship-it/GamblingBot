"""FastAPI dependency providers.

The session factory is stored on ``app.state`` by :func:`create_app`, so tests
can inject an in-memory database simply by passing their own factory. The
request-scoped session is read-only here — it is never committed.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Iterator[Session]:
    """Yield a request-scoped SQLAlchemy session, always closed afterwards."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()
