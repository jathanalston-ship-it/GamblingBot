"""Append-only thesis evaluations per tracked trade (table: ``trade_evaluations``).

One row per (tracked trade, reevaluation) — every market scan appends one for
each OPEN trade. Rows are **never updated or deleted** (the repository refuses),
so the thesis history of a trade is a faithful, replayable record.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class TradeEvaluation(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "trade_evaluations"

    trade_uid: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    current_conviction: Mapped[float | None] = mapped_column(Float, nullable=True)
    conviction_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_trend: Mapped[str] = mapped_column(String(8), nullable=False)
    rs_trend: Mapped[str] = mapped_column(String(8), nullable=False)
    volume_trend: Mapped[str] = mapped_column(String(8), nullable=False)
    atr_expansion: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime_at_entry: Mapped[str | None] = mapped_column(String(16), nullable=True)
    regime_now: Mapped[str | None] = mapped_column(String(16), nullable=True)
    regime_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sector_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    analog_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    thesis_strength: Mapped[float] = mapped_column(Float, nullable=False)
    thesis_stability: Mapped[float] = mapped_column(Float, nullable=False)
    health: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    # The hot per-trade history query at thousands of trades × many evaluations.
    __table_args__ = (Index("ix_trade_evaluations_uid_at", "trade_uid", "evaluated_at"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_uid": self.trade_uid,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "current_conviction": self.current_conviction,
            "conviction_delta": self.conviction_delta,
            "momentum_trend": self.momentum_trend,
            "rs_trend": self.rs_trend,
            "volume_trend": self.volume_trend,
            "atr_expansion": self.atr_expansion,
            "regime_at_entry": self.regime_at_entry,
            "regime_now": self.regime_now,
            "regime_changed": self.regime_changed,
            "sector_delta": self.sector_delta,
            "analog_delta": self.analog_delta,
            "thesis_strength": self.thesis_strength,
            "thesis_stability": self.thesis_stability,
            "health": self.health,
            "action": self.action,
            "reasons": self.reasons,
            "price": self.price,
            "stop_breached": self.stop_breached,
        }
