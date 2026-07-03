"""Repositories for the brokerage-simulation tables.

``BrokerAccountHistoryRepository`` and ``BrokerOrderEventRepository`` are
**append-only**: ``delete`` raises, because the account trail and the order
lifecycle are the audit record — history is never rewritten.
"""

from __future__ import annotations

import datetime as dt
from typing import Never

from sqlalchemy import select

from momentum.persistence.models.broker import (
    BrokerAccount,
    BrokerAccountHistory,
    BrokerFill,
    BrokerOrderEvent,
    BrokerOrderRow,
    BrokerPosition,
)
from momentum.persistence.repositories.base import Repository


class BrokerAccountRepository(Repository[BrokerAccount]):
    model = BrokerAccount

    def by_account_id(self, account_id: str) -> BrokerAccount | None:
        return self.session.scalars(
            select(BrokerAccount).where(BrokerAccount.account_id == account_id)
        ).first()

    def all_accounts(self) -> list[BrokerAccount]:
        return list(self.session.scalars(select(BrokerAccount).order_by(BrokerAccount.id)).all())


class BrokerAccountHistoryRepository(Repository[BrokerAccountHistory]):
    model = BrokerAccountHistory

    def delete(self, entity: BrokerAccountHistory) -> Never:
        raise TypeError("broker_account_history is append-only; rows are never deleted")

    def for_account(
        self,
        account_id: str,
        *,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        limit: int = 500,
    ) -> list[BrokerAccountHistory]:
        stmt = select(BrokerAccountHistory).where(BrokerAccountHistory.account_id == account_id)
        if start is not None:
            stmt = stmt.where(BrokerAccountHistory.ts >= start)
        if end is not None:
            stmt = stmt.where(BrokerAccountHistory.ts <= end)
        stmt = stmt.order_by(BrokerAccountHistory.ts.desc(), BrokerAccountHistory.id.desc()).limit(
            limit
        )
        return list(self.session.scalars(stmt).all())

    def equity_series(self, account_id: str, *, limit: int = 2000) -> list[float]:
        """Oldest-first equity values (feeds drawdown/sharpe)."""
        stmt = (
            select(BrokerAccountHistory.equity)
            .where(BrokerAccountHistory.account_id == account_id)
            .order_by(BrokerAccountHistory.ts.asc(), BrokerAccountHistory.id.asc())
            .limit(limit)
        )
        return [float(v) for v in self.session.scalars(stmt).all()]


class BrokerOrderRepository(Repository[BrokerOrderRow]):
    model = BrokerOrderRow

    def by_order_id(self, order_id: str) -> BrokerOrderRow | None:
        return self.session.scalars(
            select(BrokerOrderRow).where(BrokerOrderRow.order_id == order_id)
        ).first()

    def for_account(
        self, account_id: str, *, statuses: list[str] | None = None, limit: int = 100
    ) -> list[BrokerOrderRow]:
        stmt = select(BrokerOrderRow).where(BrokerOrderRow.account_id == account_id)
        if statuses:
            stmt = stmt.where(BrokerOrderRow.status.in_(statuses))
        stmt = stmt.order_by(BrokerOrderRow.created_ts.desc(), BrokerOrderRow.id.desc()).limit(
            limit
        )
        return list(self.session.scalars(stmt).all())

    def open_orders(self, account_id: str | None = None) -> list[BrokerOrderRow]:
        open_statuses = ["submitted", "accepted", "working", "partially_filled"]
        stmt = select(BrokerOrderRow).where(BrokerOrderRow.status.in_(open_statuses))
        if account_id is not None:
            stmt = stmt.where(BrokerOrderRow.account_id == account_id)
        return list(self.session.scalars(stmt.order_by(BrokerOrderRow.id.asc())).all())

    def children_of(self, order_id: str) -> list[BrokerOrderRow]:
        return list(
            self.session.scalars(
                select(BrokerOrderRow).where(BrokerOrderRow.parent_order_id == order_id)
            ).all()
        )

    def oco_siblings(self, oco_group: str, *, exclude: str | None = None) -> list[BrokerOrderRow]:
        stmt = select(BrokerOrderRow).where(BrokerOrderRow.oco_group == oco_group)
        if exclude is not None:
            stmt = stmt.where(BrokerOrderRow.order_id != exclude)
        return list(self.session.scalars(stmt).all())


class BrokerOrderEventRepository(Repository[BrokerOrderEvent]):
    model = BrokerOrderEvent

    def delete(self, entity: BrokerOrderEvent) -> Never:
        raise TypeError("broker_order_events is append-only; rows are never deleted")

    def for_order(self, order_id: str) -> list[BrokerOrderEvent]:
        return list(
            self.session.scalars(
                select(BrokerOrderEvent)
                .where(BrokerOrderEvent.order_id == order_id)
                .order_by(BrokerOrderEvent.ts.asc(), BrokerOrderEvent.id.asc())
            ).all()
        )


class BrokerFillRepository(Repository[BrokerFill]):
    model = BrokerFill

    def for_account(self, account_id: str, *, limit: int = 100) -> list[BrokerFill]:
        return list(
            self.session.scalars(
                select(BrokerFill)
                .where(BrokerFill.account_id == account_id)
                .order_by(BrokerFill.ts.desc(), BrokerFill.id.desc())
                .limit(limit)
            ).all()
        )

    def for_order(self, order_id: str) -> list[BrokerFill]:
        return list(
            self.session.scalars(
                select(BrokerFill)
                .where(BrokerFill.order_id == order_id)
                .order_by(BrokerFill.ts.asc(), BrokerFill.id.asc())
            ).all()
        )


class BrokerPositionRepository(Repository[BrokerPosition]):
    model = BrokerPosition

    def open_position(
        self, account_id: str, symbol: str, *, instrument: str = "shares"
    ) -> BrokerPosition | None:
        return self.session.scalars(
            select(BrokerPosition).where(
                BrokerPosition.account_id == account_id,
                BrokerPosition.symbol == symbol.upper(),
                BrokerPosition.instrument == instrument,
                BrokerPosition.is_open.is_(True),
            )
        ).first()

    def open_for_account(self, account_id: str) -> list[BrokerPosition]:
        return list(
            self.session.scalars(
                select(BrokerPosition)
                .where(
                    BrokerPosition.account_id == account_id,
                    BrokerPosition.is_open.is_(True),
                )
                .order_by(BrokerPosition.symbol.asc())
            ).all()
        )

    def all_for_account(self, account_id: str, *, limit: int = 500) -> list[BrokerPosition]:
        return list(
            self.session.scalars(
                select(BrokerPosition)
                .where(BrokerPosition.account_id == account_id)
                .order_by(BrokerPosition.is_open.desc(), BrokerPosition.opened_at.desc())
                .limit(limit)
            ).all()
        )
