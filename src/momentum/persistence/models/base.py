"""Declarative base and shared column mixins for all ORM models.

Every table in the schema inherits two mixins so the platform's auditability
guarantees hold uniformly:

  * ``IntPKMixin``      -> a surrogate, autoincrementing integer primary key.
  * ``TimestampMixin``  -> ``created_at`` / ``updated_at`` maintained by the DB.

A naming convention is attached to the shared ``MetaData`` so that indexes,
unique constraints and foreign keys receive deterministic names. This is
essential for (a) clean Alembic autogeneration and (b) SQLite "batch" migrations,
which recreate a table to emulate ``ALTER`` and need named constraints to do so.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic names for ix/uq/ck/fk/pk -> stable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base; owns the ``MetaData`` every table registers on."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IntPKMixin:
    """Surrogate, autoincrementing integer primary key (``id``)."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class TimestampMixin:
    """Row audit timestamps, written by the database server clock.

    ``created_at`` is set once on INSERT; ``updated_at`` is refreshed on every
    UPDATE via ``onupdate``. ``created_at`` is indexed because it is a common
    sort/filter axis for audit queries ("everything written today").
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
