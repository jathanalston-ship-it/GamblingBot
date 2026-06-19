"""Parameter-optimization / walk-forward results (table: ``optimization_results``).

One row per parameter set evaluated within a study. Stores the parameters, the
objective score and the headline performance/risk metrics for that set, plus the
walk-forward fold and window so in-sample vs out-of-sample robustness is explicit.
``run_id`` links a result to the backtest records (trades, snapshots) it produced.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Boolean, Date, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class OptimizationResult(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "optimization_results"

    # --- study identity -----------------------------------------------------
    study_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # The optimization study/experiment this result belongs to.
    optimizer: Mapped[str] = mapped_column(String(24), nullable=False, default="grid")
    # Search method: "grid" | "random" | "optuna_tpe" | ...
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Backtest run produced for this parameter set (links to trades/snapshots).
    param_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Stable hash of ``parameters`` (dedupe + reproducibility).
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # The exact parameter set evaluated.

    # --- objective & sampling ----------------------------------------------
    objective: Mapped[str] = mapped_column(String(32), nullable=False, default="sharpe")
    # Metric being optimised (e.g. "sharpe", "expectancy_r", "calmar").
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # Score of this set on the objective (indexed for "best of study" queries).
    sample: Mapped[str] = mapped_column(String(16), nullable=False, default="full")
    # "in_sample" | "out_of_sample" | "full" — guards against overfitting.
    fold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Walk-forward fold index (NULL for non-folded studies).
    window_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # Start of the data window evaluated.
    window_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # End of the data window evaluated.

    # --- headline performance / risk ---------------------------------------
    cagr: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Compound annual growth rate.
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised Sharpe.
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised Sortino.
    calmar: Mapped[float | None] = mapped_column(Float, nullable=True)
    # CAGR / |max drawdown|.
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Worst peak-to-trough decline.
    volatility_annual: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised volatility.
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fraction of winning trades.
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Gross profit / gross loss.
    expectancy_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Average R per trade for this set.
    num_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Trade count (sample size / significance).
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Portfolio turnover (cost sensitivity).

    # --- selection ----------------------------------------------------------
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Rank within the study on the objective.
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # Whether this set was chosen for deployment.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Extra diagnostics (per-fold breakdown, secondary metrics, ...).

    __table_args__ = (
        # A given parameter set appears once per study / sample / fold.
        UniqueConstraint(
            "study_name",
            "param_hash",
            "sample",
            "fold",
            name="uq_optresult_study_param_sample_fold",
        ),
        # "Best parameter sets in this study" leaderboard queries.
        Index("ix_optimization_results_study_objective", "study_name", "objective_value"),
    )
