"""Generic repository base bound to a SQLAlchemy session.

Keeps SQL/ORM mechanics out of the business layers: services hold a session and
a repository, never raw queries. Subclasses set ``model`` and add domain
methods; the base provides the common add/get/list/delete plumbing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from momentum.persistence.models.base import Base

T = TypeVar("T", bound=Base)


class Repository(Generic[T]):
    """CRUD plumbing for a single ORM model, scoped to one ``Session``."""

    model: type[T]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: T) -> T:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Iterable[T]) -> list[T]:
        items = list(entities)
        self.session.add_all(items)
        return items

    def get(self, entity_id: int) -> T | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, limit: int | None = None) -> Sequence[T]:
        stmt = select(self.model)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def delete(self, entity: T) -> None:
        self.session.delete(entity)

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(self.model)) or 0)
