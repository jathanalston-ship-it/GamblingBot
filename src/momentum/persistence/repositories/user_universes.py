"""Data access for user-defined scanner universes (``user_universes``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from momentum.persistence.models.user_universe import UserUniverse
from momentum.persistence.repositories.base import Repository


class UserUniverseRepository(Repository[UserUniverse]):
    """CRUD + upsert-by-key for user universes."""

    model = UserUniverse

    def by_key(self, key: str) -> UserUniverse | None:
        stmt = select(UserUniverse).where(UserUniverse.key == key)
        return self.session.scalars(stmt).one_or_none()

    def all_ordered(self) -> list[UserUniverse]:
        """Every user universe, newest first."""
        stmt = select(UserUniverse).order_by(UserUniverse.created_at.desc(), UserUniverse.id.desc())
        return list(self.session.scalars(stmt).all())

    def upsert(
        self,
        *,
        key: str,
        label: str,
        kind: str,
        symbols: list[str],
        description: str | None = None,
        sectors: dict[str, str] | None = None,
        source: dict[str, Any] | None = None,
    ) -> UserUniverse:
        """Create or replace the universe stored under ``key``."""
        row = self.by_key(key)
        if row is None:
            row = UserUniverse(key=key)
            self.session.add(row)
        row.label = label
        row.kind = kind
        row.symbols = symbols
        row.description = description
        row.sectors = sectors
        row.source = source
        self.session.flush()
        return row

    def delete_by_key(self, key: str) -> bool:
        """Delete a universe by key; returns whether a row was removed."""
        row = self.by_key(key)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True
