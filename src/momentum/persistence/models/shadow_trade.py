"""Shadow trades (table: ``shadow_trades``) — orders generated, never submitted.

One row per shadow entry: the order the strategy WOULD have placed, the
expected fill (spread + slippage modeled from the live bar), the reference
price it was decided at, and — as later scans manage it — the expected
exit, P&L and R. Shadow rows never touch the paper journal, the brokerage
venue or any live broker; they exist to grade execution assumptions before
a single real order is risked.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ShadowTrade(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "shadow_trades"

    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entered_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    conviction_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Entry: what we expected to pay vs the price the decision was made at.
    expected_entry: Mapped[float] = mapped_column(Float, nullable=False)
    reference_entry: Mapped[float] = mapped_column(Float, nullable=False)
    entry_slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    stop_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open", index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_r: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Tracked forward on every evaluation.
    mfe_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_eval_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_shadow_trades_run_symbol"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "run_id": self.run_id,
            "entered_at": self.entered_at.isoformat() if self.entered_at else None,
            "quantity": self.quantity,
            "conviction_score": self.conviction_score,
            "expected_entry": self.expected_entry,
            "reference_entry": self.reference_entry,
            "entry_slippage_bps": self.entry_slippage_bps,
            "stop_price": self.stop_price,
            "current_stop": self.current_stop,
            "target_price": self.target_price,
            "status": self.status,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "exit_run_id": self.exit_run_id,
            "expected_exit": self.expected_exit,
            "reference_exit": self.reference_exit,
            "exit_slippage_bps": self.exit_slippage_bps,
            "exit_reason": self.exit_reason,
            "expected_pnl": self.expected_pnl,
            "expected_r": self.expected_r,
            "mfe_price": self.mfe_price,
            "mae_price": self.mae_price,
            "last_price": self.last_price,
            "last_eval_at": self.last_eval_at.isoformat() if self.last_eval_at else None,
            "evaluations": self.evaluations,
        }
