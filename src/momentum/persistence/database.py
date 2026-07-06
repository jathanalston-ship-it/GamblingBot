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


def _scalar_default_literal(column: object) -> str | None:
    """A SQL literal for a column's *scalar* Python default (``default="managed"``
    → ``'managed'``), or ``None`` when there is no such default (callables,
    sequences and SQL-expression defaults are not back-fillable here)."""
    default = getattr(column, "default", None)
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg  # the constant passed to mapped_column(default=...)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def reconcile_schema(engine: Engine) -> None:
    """Idempotently bring an existing database up to the current ORM schema.

    Desktop databases are created by :func:`create_all` (not Alembic), so when the
    app is upgraded to a build that added tables or columns, the old file must
    self-heal — otherwise a ``SELECT`` on a model whose table is missing a new
    column fails with "no such column" (a 500 on the first screen that reads it).

    This creates any missing tables and ``ADD COLUMN``s any missing column declared
    on the ORM models. A **non-nullable** column with a scalar default (e.g.
    ``default="managed"``) is added ``NOT NULL DEFAULT <value>`` so SQLite
    back-fills existing rows — without that, an added-as-nullable column leaves old
    rows ``NULL`` and a non-optional Pydantic field then 500s on read. Existing
    non-nullable scalar-default columns are also back-filled where a prior run
    added them as nullable. Non-nullable columns without any default are left to a
    real migration. Safe to run on every startup; a no-op once current.
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
                default_sql = _scalar_default_literal(column)
                if column.name in present:
                    # Heal rows a previous (nullable) reconcile left NULL.
                    if not column.nullable and default_sql is not None:
                        conn.execute(
                            text(
                                f'UPDATE "{table.name}" SET "{column.name}" = {default_sql} '
                                f'WHERE "{column.name}" IS NULL'
                            )
                        )
                    continue
                if not column.nullable and default_sql is None and column.server_default is None:
                    _log.warning(
                        "skipping non-nullable column %s.%s with no default; needs a migration",
                        table.name,
                        column.name,
                    )
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                # A DEFAULT lets SQLite back-fill existing rows, which in turn makes
                # NOT NULL safe to add to a populated table.
                if default_sql is not None:
                    ddl += f" DEFAULT {default_sql}"
                    if not column.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
                _log.info("reconciled schema: added %s.%s", table.name, column.name)


def drop_all(engine: Engine) -> None:
    """Drop every table (tests only)."""
    Base.metadata.drop_all(engine)
