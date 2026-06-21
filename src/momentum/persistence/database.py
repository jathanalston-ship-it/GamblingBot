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

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from momentum.persistence.models.base import Base

_log = logging.getLogger(__name__)

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


def reconcile_schema(engine: Engine) -> None:
    """Idempotently bring an existing database up to the current ORM schema.

    Desktop databases are created by :func:`create_all` (not Alembic), so when the
    app is upgraded to a build that added tables or columns, the old file must
    self-heal — otherwise a ``SELECT`` on a model whose table is missing a new
    column fails with "no such column" (a 500 on the first screen that reads it).

    This creates any missing tables and ``ADD COLUMN``s any missing **nullable**
    column declared on the ORM models. It is safe to run on every startup and is a
    no-op once the schema is current. Non-nullable columns without a default are
    left to a real migration (they cannot be added to a populated table safely).
    """
    Base.metadata.create_all(engine)  # any brand-new tables
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue  # just created above with all its columns
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    _log.warning(
                        "skipping non-nullable column %s.%s with no default; needs a migration",
                        table.name,
                        column.name,
                    )
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
                )
                _log.info("reconciled schema: added %s.%s", table.name, column.name)


def drop_all(engine: Engine) -> None:
    """Drop every table (tests only)."""
    Base.metadata.drop_all(engine)
