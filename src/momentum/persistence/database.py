"""Engine / session factory and SQLite pragmas.

Central place to construct the SQLAlchemy ``Engine`` and ``Session`` factory.
SQLite is configured with WAL journaling and enforced foreign keys for research
durability; the same code points at Postgres in production by changing the URL.

In production the schema is owned by Alembic migrations. ``create_all`` is a
convenience for tests and quick local research only.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from momentum.persistence.models.base import Base

DEFAULT_DATABASE_URL = "sqlite:///data/momentum.db"


def get_database_url() -> str:
    """Resolve the database URL from the environment, with a research default."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_db_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create an Engine and apply SQLite pragmas when on SQLite."""
    engine = create_engine(url or get_database_url(), echo=echo, future=True)

    if engine.url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a configured ``Session`` factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    """Create every table from the ORM metadata (tests / local research only)."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop every table (tests only)."""
    Base.metadata.drop_all(engine)
