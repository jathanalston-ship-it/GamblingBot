# Implementation Roadmap

Build order respects the dependency graph (bottom-up): you cannot size a trade before you can measure volatility, and you cannot measure volatility before you have clean bars. Risk is built early and hardened continuously — it is the product.

> No code is written yet. This is the intended sequence once implementation begins.

---

## Phase 0 — Foundations
**Goal:** the skeleton everything plugs into.
- `core/`: config loading + validation, logging, clock protocol, domain `types`/`enums`.
- `persistence/`: engine/session, base repository, `runs` registry, Alembic baseline.
- **Exit:** a `run` can be created, configured from YAML, and logged with a reproducible config hash.

## Phase 1 — Data layer
**Goal:** trustworthy, point-in-time price history.
- `data/`: `MarketDataProvider` interface + one concrete adapter (yfinance for free research), calendar, corporate-action adjustment, validation gates, cache, ingestion.
- `persistence/models`: `instruments`, `daily_bars`, `corporate_actions`.
- **Exit:** ingest N years of adjusted daily bars for a symbol list; validation passes; re-running is idempotent.

## Phase 2 — Universe & signals (the simple strategy)
**Goal:** generate breakout signals, nothing more.
- `universe/`: screener + filters + point-in-time selector.
- `signals/`: indicators, breakout, momentum ranking, regime filter, `signal_generator`.
- **Exit:** for any historical date, produce the eligible universe and its signals — with the feature vector persisted.

## Phase 3 — Risk engine ★ (the focus)
**Goal:** sophisticated, fully-tested risk control. Spend the most time here.
- Per-trade: `volatility`, `position_sizing`, `stops`.
- Portfolio: `exposure`, `correlation`, `heat`, `drawdown`, `limits`.
- Gateway: `risk_manager.evaluate()` + `RiskAssessment` persistence.
- **Testing:** property-based tests (Hypothesis) asserting invariants — e.g. *a −1R loss never exceeds `risk_per_trade` of equity*, *heat never exceeds its ceiling*, *trailing stops are monotonic*.
- **Exit:** every sizing/stop/limit path has tests; no order can be produced that violates a configured limit.

## Phase 4 — Backtest, portfolio & execution sim
**Goal:** simulate the full pipeline deterministically.
- `portfolio/`: portfolio, position, allocator, rebalancer.
- `execution/`: broker interface, slippage/commission, paper broker.
- `backtest/`: event engine, market sim, walk-forward.
- **Exit:** an end-to-end backtest runs reproducibly (same seed → same trades) and persists trades/equity.

## Phase 5 — Analytics & reporting
**Goal:** measure everything.
- `analytics/`: performance, trade statistics, drawdown, trade/R analysis, attribution.
- `reporting/`: Plotly plots, tearsheet, run reports.
- **Exit:** a backtest produces a full HTML tearsheet (equity curve, R-distribution, drawdown, expectancy).

## Phase 6 — Service & orchestration
**Goal:** drive and inspect the system.
- `orchestration/`: pipeline wiring + scheduler.
- `api/` (FastAPI) + `cli/` (Typer).
- **Exit:** `mrp backtest`, `mrp scan`, and `mrp serve` (read APIs for signals/risk/performance) all work.

## Phase 7 — Paper trading
**Goal:** prove the live path with no money at risk.
- Swap clock→`LiveClock`, data→live feed, broker→`paper_broker`. **Core logic unchanged.**
- Run the EOD pipeline on schedule; shadow live data.
- **Exit:** sustained paper run; live decisions match what the backtester would have produced on the same data.

## Phase 8 — Live execution (gated)
**Goal:** real orders, carefully.
- `live_broker` adapter; reconciliation; alerting on every `risk_event`.
- Hard pre-flight checks; circuit breakers verified against the live account.
- **Exit:** small-size live trading with monitoring; kill-switches validated end-to-end.

---

## Cross-phase, always-on
- **Tests first for risk** — `risk/` and `analytics/` are the most heavily tested packages.
- **Determinism** — every run records config hash, git commit and RNG seed.
- **Auditability** — no decision ships without a persisted record and a reason.
- **No look-ahead** — enforced by the clock abstraction and bar-close discipline in the backtester.
