"""Market-regime classification time series (table: ``market_regimes``).

One row per (date, benchmark, model version) recording the prevailing market
environment. Signals, trades and portfolio snapshots reference the regime in
force at their time, so performance can later be attributed by regime and the
strategy's regime filter is fully auditable.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, Float, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class MarketRegime(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "market_regimes"

    # --- identity of the classification -------------------------------------
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # Trading date this classification applies to.
    benchmark_symbol: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SPY", index=True
    )
    # Index used to characterise the market (e.g. SPY, QQQ, IWM).
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    # Version of the regime model that produced the row (reproducibility).

    # --- the classification -------------------------------------------------
    regime: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Headline label: "bull" | "bear" | "neutral".
    trend_state: Mapped[str] = mapped_column(String(16), nullable=False, default="sideways")
    # Trend component: "uptrend" | "downtrend" | "sideways".
    volatility_state: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    # Volatility component: "low" | "normal" | "high" | "extreme".
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Continuous regime score (e.g. -1 strongly bearish .. +1 strongly bullish).
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Model confidence in the label, 0..1.

    # --- supporting indicators (the evidence) -------------------------------
    benchmark_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Benchmark close on ``as_of``.
    ma_fast: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fast moving average of the benchmark (e.g. 50DMA).
    ma_slow: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Slow moving average of the benchmark (e.g. 200DMA) — the core trend gate.
    adx: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Trend-strength (ADX) of the benchmark.
    realized_vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised realised volatility of the benchmark.
    breadth: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Market breadth, e.g. % of universe above its 200DMA (optional).
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Free-form extra indicators / diagnostics for this classification.

    __table_args__ = (
        # At most one classification per date / benchmark / model version.
        UniqueConstraint(
            "as_of", "benchmark_symbol", "model_version", name="uq_regime_asof_benchmark_model"
        ),
        # Fast "what regime were we in on date X / over range" lookups.
        Index("ix_market_regimes_asof_regime", "as_of", "regime"),
    )
