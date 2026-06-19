"""Position-sizing / risk-gateway decisions (table: ``position_sizes``).

One row per signal evaluated by the risk engine. It captures *all* sizing
inputs and the verdict, so the question "why this many shares (or why none)?"
is answerable for every trade. This is the persisted ``RiskAssessment``.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:
    from momentum.persistence.models.signal import Signal


class PositionSize(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "position_sizes"

    # --- linkage ------------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Backtest / live session grouping key.
    signal_id: Mapped[int] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    # The signal this sizing decision is for (one sizing per signal).
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Denormalised ticker for convenient querying.

    # --- method & verdict ---------------------------------------------------
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="fixed_fractional_risk")
    # "fixed_fractional_risk" | "vol_target" | "fractional_kelly".
    verdict: Mapped[str] = mapped_column(String(8), nullable=False, default="approve", index=True)
    # Gateway outcome: "approve" | "resize" | "veto".
    binding_constraint: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # Which rule resized/vetoed (e.g. "portfolio_heat", "correlation", "sector").
    reasons: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Human-readable explanation list for the verdict.

    # --- sizing inputs ------------------------------------------------------
    account_equity: Mapped[float] = mapped_column(Float, nullable=False)
    # Account equity at decision time.
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, nullable=False)
    # Fraction of equity risked on this trade (the "R" budget), e.g. 0.0075.
    risk_dollars: Mapped[float] = mapped_column(Float, nullable=False)
    # equity * risk_per_trade_pct -> the dollar value of 1R.
    entry_reference: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Intended entry price.
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Initial protective stop (entry - k*ATR).
    stop_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # entry - stop = risk per share.
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ATR used for the stop / risk-per-share.
    vol_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised volatility estimate (used by the vol-target method).

    # --- sizing outputs -----------------------------------------------------
    target_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Shares implied by the sizing math before portfolio constraints.
    approved_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Shares actually approved after caps / heat / limits.
    target_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    # approved_shares * entry_reference.
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    # target_notional / account_equity.
    portfolio_heat_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Portfolio open-risk fraction before adding this position.
    portfolio_heat_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Projected portfolio heat if approved.

    # --- relationships ------------------------------------------------------
    signal: Mapped["Signal"] = relationship("Signal")

    __table_args__ = (
        # Filter a run's decisions by outcome (e.g. all vetoes for a backtest).
        Index("ix_position_sizes_run_verdict", "run_id", "verdict"),
    )
