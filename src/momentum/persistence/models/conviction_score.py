"""Persisted conviction scores (table: ``conviction_scores``).

One row per scored setup: the 0-100 score and band, the eight normalized
component scores (as queryable columns), the full explainable breakdown (JSON),
and links to the originating trade / signal. ``from_result`` maps a
:class:`~momentum.conviction.engine.ConvictionResult` onto a row.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:  # avoid a persistence <-> conviction import cycle
    from momentum.conviction.engine import ConvictionResult


class ConvictionScore(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "conviction_scores"

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
    score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    band: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    config_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- normalized component scores (0..1), one per input ------------------
    regime_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_ath: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    breadth: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_edge: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- full explainable breakdown -----------------------------------------
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_conviction_scores_symbol_as_of", "symbol", "as_of"),
        Index("ix_conviction_scores_run_band", "run_id", "band"),
    )

    @classmethod
    def from_result(
        cls,
        result: ConvictionResult,
        *,
        symbol: str,
        run_id: str | None = None,
        as_of: dt.date | None = None,
        ts: dt.datetime | None = None,
        trade_id: int | None = None,
        signal_id: int | None = None,
    ) -> ConvictionScore:
        nm = result.normalized_map()
        return cls(
            run_id=run_id,
            symbol=symbol.upper(),
            as_of=as_of or dt.date.today(),
            ts=ts,
            trade_id=trade_id,
            signal_id=signal_id,
            score=result.score,
            band=result.band.value,
            model_version=result.model_version,
            config_hash=result.config_hash,
            regime_score=nm["market_regime"],
            sector_strength=nm["sector_strength"],
            relative_volume=nm["relative_volume"],
            distance_to_ath=nm["distance_to_ath"],
            trend_strength=nm["trend_strength"],
            breadth=nm["breadth"],
            momentum_score=nm["momentum_score"],
            historical_edge=nm["historical_similar_setups"],
            breakdown=result.to_dict(),
        )
