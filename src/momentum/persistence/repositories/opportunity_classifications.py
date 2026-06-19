"""Data access for persisted Home-Run-opportunity classifications."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from momentum.persistence.models.opportunity_classification import OpportunityClassification
from momentum.persistence.repositories.base import Repository

if TYPE_CHECKING:
    from momentum.opportunity.engine import OpportunityResult


class OpportunityClassificationRepository(Repository[OpportunityClassification]):
    """CRUD + queries for the ``opportunity_classifications`` table."""

    model = OpportunityClassification

    def save_result(
        self,
        result: OpportunityResult,
        *,
        symbol: str,
        run_id: str | None = None,
        as_of: dt.date | None = None,
        ts: dt.datetime | None = None,
        trade_id: int | None = None,
        signal_id: int | None = None,
    ) -> OpportunityClassification:
        """Persist an :class:`OpportunityResult` and return the stored row."""
        row = OpportunityClassification.from_result(
            result,
            symbol=symbol,
            run_id=run_id,
            as_of=as_of,
            ts=ts,
            trade_id=trade_id,
            signal_id=signal_id,
        )
        return self.add(row)

    def for_symbol(self, symbol: str, run_id: str | None = None) -> list[OpportunityClassification]:
        stmt = select(OpportunityClassification).where(
            OpportunityClassification.symbol == symbol.upper()
        )
        if run_id is not None:
            stmt = stmt.where(OpportunityClassification.run_id == run_id)
        return list(
            self.session.scalars(stmt.order_by(OpportunityClassification.as_of.desc())).all()
        )

    def by_tier(self, tier: str, run_id: str | None = None) -> list[OpportunityClassification]:
        stmt = select(OpportunityClassification).where(OpportunityClassification.tier == tier)
        if run_id is not None:
            stmt = stmt.where(OpportunityClassification.run_id == run_id)
        return list(
            self.session.scalars(stmt.order_by(OpportunityClassification.score.desc())).all()
        )

    def tier_mix(self, run_id: str | None = None) -> dict[str, int]:
        """Count classifications per tier (the realized opportunity distribution)."""
        stmt = select(OpportunityClassification.tier, func.count()).group_by(
            OpportunityClassification.tier
        )
        if run_id is not None:
            stmt = stmt.where(OpportunityClassification.run_id == run_id)
        return {tier: int(count) for tier, count in self.session.execute(stmt).all()}

    def home_run_rate(self, run_id: str | None = None) -> float:
        """Realized fraction of classifications in the Home-Run tier (0 when empty).

        The headline rarity metric — this should stay under the configured
        ``target_home_run_rate`` (< 5%).
        """
        mix = self.tier_mix(run_id)
        total = sum(mix.values())
        return mix.get("home_run", 0) / total if total else 0.0
