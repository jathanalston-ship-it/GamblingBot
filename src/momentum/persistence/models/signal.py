"""Trading signals emitted by the strategy layer (table: ``signals``).

A signal is the *simple* strategy's only output: "enter/exit this symbol now".
It carries no sizing and no money — that is the job of ``position_sizes``. The
full feature vector that produced the signal is stored for auditability and
later analysis.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:
    from momentum.persistence.models.market_regime import MarketRegime


class Signal(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "signals"

    # --- provenance ---------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Groups every record produced by one backtest / live session.
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="backtest")
    # Origin: "backtest" | "paper" | "live".
    strategy: Mapped[str] = mapped_column(String(48), nullable=False, default="breakout")
    # Name/version of the strategy that emitted the signal.

    # --- what & when --------------------------------------------------------
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Ticker the signal refers to.
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Exact timestamp of the (closed) bar that generated the signal.
    session_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # Trading session date (date-only convenience for grouping/joins).
    signal_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # "entry" | "exit" | "scale_in" | "scale_out".
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="long")
    # "long" | "short".

    # --- the breakout evidence ---------------------------------------------
    strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Conviction/score of the signal (strategy-defined, e.g. 0..1).
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Cross-sectional momentum rank/score used to qualify the entry.
    breakout_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Price level that was broken (e.g. N-day high / Donchian upper band).
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Price at signal time (typically the bar close) — the sizing reference.
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ATR at signal time; flows downstream into stop placement and sizing.

    # --- context & lifecycle ------------------------------------------------
    regime_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_regimes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Market regime in force when the signal fired (nullable).
    features: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Full feature vector behind the signal (indicators, ranks, filters).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generated", index=True)
    # Lifecycle: "generated" | "accepted" | "rejected" | "expired".

    # --- relationships ------------------------------------------------------
    regime: Mapped["MarketRegime | None"] = relationship("MarketRegime")

    __table_args__ = (
        # Per-symbol time-series scans (charts, "signals for AAPL over range").
        Index("ix_signals_symbol_ts", "symbol", "ts"),
        # All signals for one run/symbol.
        Index("ix_signals_run_symbol", "run_id", "symbol"),
    )
