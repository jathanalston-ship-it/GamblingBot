"""Persisted Home-Run-opportunity classifications (table: ``opportunity_classifications``).

One row per classified setup: the tier and 0-100 opportunity score, the raw
new-ATH flag, the six normalized component scores (as queryable columns), the
full explainable breakdown and gate outcomes (JSON), and links to the originating
trade / signal. ``from_result`` maps an
:class:`~momentum.opportunity.engine.OpportunityResult` onto a row.

Storing *every* classification — not just Home Runs — is what lets the platform
audit the realized tier mix and confirm Home Runs stay under the rarity target.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:  # avoid a persistence <-> opportunity import cycle
    from momentum.opportunity.engine import OpportunityResult


class OpportunityClassification(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "opportunity_classifications"

    # --- identity / linkage -------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    ts: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True
    )
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- result -------------------------------------------------------------
    tier: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    new_ath: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    config_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- normalized component scores (0..1), one per input ------------------
    new_ath_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector_leadership: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_edge: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- full explainable breakdown + gate outcomes -------------------------
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_opportunity_classifications_symbol_as_of", "symbol", "as_of"),
        Index("ix_opportunity_classifications_run_tier", "run_id", "tier"),
    )

    @classmethod
    def from_result(
        cls,
        result: OpportunityResult,
        *,
        symbol: str,
        run_id: str | None = None,
        as_of: dt.date | None = None,
        ts: dt.datetime | None = None,
        trade_id: int | None = None,
        signal_id: int | None = None,
    ) -> OpportunityClassification:
        nm = result.normalized_map()
        return cls(
            run_id=run_id,
            symbol=symbol.upper(),
            as_of=as_of or dt.date.today(),
            ts=ts,
            trade_id=trade_id,
            signal_id=signal_id,
            tier=result.tier.value,
            score=result.score,
            new_ath=result.new_ath,
            model_version=result.model_version,
            config_hash=result.config_hash,
            new_ath_score=nm["new_ath"],
            momentum_score=nm["momentum"],
            relative_volume=nm["relative_volume"],
            regime_score=nm["market_regime"],
            sector_leadership=nm["sector_leadership"],
            historical_edge=nm["historical_analogs"],
            breakdown=result.to_dict(),
        )
