"""Momentum Research Platform (MRP).

A systematic momentum-breakout research & trading platform for US equities.

Design contract:
  * Strategy is simple (breakout + momentum + regime filter).
  * Risk management is sophisticated and centralized (see momentum.risk).
  * Every decision is data-driven, reproducible and fully auditable.
  * The SAME code path runs in backtest, paper and live (see momentum.core.clock).

Sub-packages:
  core          Cross-cutting primitives (config, logging, clock, types).
  data          Market-data ingestion, adjustment, validation, caching.
  universe      Tradeable-universe screening (survivorship-bias-free).
  signals       Entry/exit signal generation (the "simple" strategy).
  risk          Centralized risk engine (the focus of this platform).
  portfolio     Account/position state and target construction.
  execution     Broker abstraction + order management (paper/live).
  backtest      Deterministic event-driven simulator.
  analytics     Performance and trade statistics.
  reporting     Plotly visualizations, tearsheets, run reports.
  persistence   SQLAlchemy models, repositories, audit log, migrations.
  api           FastAPI service layer.
  orchestration Pipeline wiring and scheduling.
  cli           Command-line entry points.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
