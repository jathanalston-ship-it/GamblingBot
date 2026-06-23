"""User-defined scanner universes (table: ``user_universes``).

One row per user universe — a custom watchlist, an imported symbol list, or a
sector universe. Built-in universes are *not* stored here (they come from
configuration); this table holds only what the user creates. The symbol list is
stored as JSON (a universe can hold thousands of symbols; a JSON blob avoids a
join table and is plenty for SQLite).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class UserUniverse(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "user_universes"

    # --- identity -----------------------------------------------------------
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Stable slug used to select the universe (e.g. "my-watchlist", "sector-energy").
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # "custom" | "imported" | "sector".
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- members ------------------------------------------------------------
    symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sectors: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    # Optional source metadata (e.g. base universe + sector for a sector universe).
    source: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("key", name="uq_user_universes_key"),)

    @property
    def size(self) -> int:
        return len(self.symbols or [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "description": self.description,
            "size": self.size,
            "symbols": list(self.symbols or []),
            "source": self.source,
        }
