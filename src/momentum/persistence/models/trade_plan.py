"""Persisted trade plan per scanned candidate (table: ``trade_plans``).

One row per ``(run_id, symbol)``: the derived entry / stop / scale-out targets /
reward:risk / suggested size for a candidate, generated at scan time from the scan
price+ATR, conviction, regime and risk budget. Read-only research output — placing
an order is a separate, deliberate action. The full plan is kept as JSON for the
panel; the key scalars are columns for querying/sorting.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, DateTime, Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class TradePlan(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "trade_plans"

    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entry: Mapped[float] = mapped_column(Float, nullable=False)
    stop: Mapped[float] = mapped_column(Float, nullable=False)
    risk_per_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_reward_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_holding_days_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_holding_days_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_risk_dollars: Mapped[float | None] = mapped_column(Float, nullable=True)

    # The full TradePlanOut payload for the panel.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_trade_plans_run_symbol"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "entry": self.entry,
            "stop": self.stop,
            "final_reward_risk": self.final_reward_risk,
            "suggested_shares": self.suggested_shares,
            "plan": self.plan,
        }
