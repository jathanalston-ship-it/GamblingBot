"""Executed trades — position round-trips (table: ``trades``).

The atomic unit of performance analysis. A trade links back to the signal that
triggered it and the sizing decision that shaped it, and records the realised
outcome in both dollars and R-multiples, plus excursion stats for stop research.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:
    from momentum.persistence.models.market_regime import MarketRegime
    from momentum.persistence.models.position_size import PositionSize
    from momentum.persistence.models.signal import Signal


class Trade(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "trades"

    # --- linkage ------------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Backtest / live session grouping key.
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Ticker traded.
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="long")
    # "long" | "short".
    entry_signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Signal that triggered entry.
    position_size_id: Mapped[int | None] = mapped_column(
        ForeignKey("position_sizes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Sizing decision that shaped the position.
    regime_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_regimes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Market regime at entry (for attribution).

    # --- entry / exit -------------------------------------------------------
    entry_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Fill timestamp of the entry.
    exit_ts: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Fill timestamp of the exit (NULL while open).
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    # Average entry fill price.
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Average exit fill price (NULL while open).
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Share quantity (absolute).
    initial_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Initial protective stop at entry.
    initial_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Dollar value of 1R at entry = quantity * (entry - initial_stop).

    # --- outcome ------------------------------------------------------------
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Realised P&L expressed in R = net_pnl / initial_risk. The core metric.
    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    # P&L before costs.
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Commissions + modelled slippage.
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    # P&L after costs.
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # net_pnl / entry notional.
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Maximum Adverse Excursion (worst unrealised loss during the hold).
    mfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Maximum Favourable Excursion (best unrealised gain during the hold).
    holding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Calendar days held.
    bars_held: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Number of bars held (granularity-independent duration).
    exit_reason: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    # "stop" | "trailing_stop" | "target" | "time_stop" | "signal_exit" | "regime_exit" | "manual".
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open", index=True)
    # "open" | "closed".

    # --- trade-intelligence context (the "why" and the conditions) ----------
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # GICS-style sector of the symbol at entry (for attribution).
    regime_label: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # Denormalised market-regime label at entry: "bullish" | "neutral" | "bearish".
    entry_reason: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    # Why we entered, e.g. "breakout_50d" | "momentum_rank" | "pullback".
    entry_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Share volume on the entry bar.
    entry_relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Entry-bar volume vs its trailing average (demand at entry).

    # --- relationships ------------------------------------------------------
    entry_signal: Mapped["Signal | None"] = relationship("Signal")
    position_size: Mapped["PositionSize | None"] = relationship("PositionSize")
    regime: Mapped["MarketRegime | None"] = relationship("MarketRegime")

    __table_args__ = (
        # Per-symbol trade history.
        Index("ix_trades_symbol_entry_ts", "symbol", "entry_ts"),
        # Open vs closed trades within a run.
        Index("ix_trades_run_status", "run_id", "status"),
    )
