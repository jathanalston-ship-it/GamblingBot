# Momentum Research Platform (MRP)

A systematic **momentum-breakout** research and trading platform for US equities — built around the thesis that durable edge comes from **risk management and position sizing**, not from predicting markets.

> **Status: architecture & scaffold only.** This repository currently contains the
> project structure, documented module stubs (docstrings, no logic), configuration
> templates and the design documents. No business logic is implemented yet.

---

## What it does (by design)

1. **Scan** US equities and build a clean, point-in-time tradeable universe.
2. **Detect** momentum breakouts with a deliberately *simple* strategy.
3. **Evaluate risk** for every candidate through a single, central risk engine.
4. **Size** positions dynamically from risk-per-trade and volatility.
5. **Hold** for days to weeks, trailing stops to ride trends.
6. **Capture** large trend moves (positive-skew exit policy).
7. **Measure** everything — detailed, reproducible performance statistics.
8. **Execute** the same code in backtest, paper and live.

## Philosophy

- **Simple strategy, sophisticated risk.** The strategy emits only "enter/exit". *All* sizing, stops and limits live in one auditable risk engine.
- **Data driven.** Every tunable is config; every decision is persisted.
- **Modular.** Strict layering; vendors and brokers sit behind interfaces.
- **Fully auditable.** Any trade — or non-trade — can be explained and reproduced from stored config, code version and seed.

### What we optimise for

This system is built for a **positive-skew payoff**, not a high hit rate. We do
**not** maximise win rate, and we do **not** maximise the number of trades.
We optimise for:

| Objective | Why |
|---|---|
| **Expectancy** (R per trade) | The primary metric — average edge per bet |
| **Profit factor** | Gross profit vs gross loss |
| **Average winner** | Winners must be large |
| **Largest winner** | The right tail carries the system |
| **Trend capture** | How much of each move we actually keep |

Consequently we **accept** — by design, not by accident:

- **Low win rates** (sub-50% is fine when winners dwarf losers),
- **Long holding periods** (winners are held for weeks; losers are cut fast),
- **Large asymmetry** between winners and losers (small fixed −1R losses, open-ended winners).

Win rate, trade count and holding time are **reported as diagnostics, never
targeted.** The analytics layer (`momentum.analytics`, see
[docs/ANALYTICS.md](docs/ANALYTICS.md)) leads every report with the objective
metrics above.

> ⚠️ Research software for systematic strategy development. Trading involves substantial risk of loss. Nothing here is financial advice.

---

## Documentation

| Doc | Contents |
|---|---|
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | System layers, data-flow & dependency diagrams, the full module catalog, one-code-path design. |
| **[docs/RISK_MANAGEMENT.md](docs/RISK_MANAGEMENT.md)** | The risk engine: sizing, stops, heat, correlation, drawdown throttle, circuit breakers, worked examples. |
| **[docs/DATA_MODEL.md](docs/DATA_MODEL.md)** | Broader target schema + ERD and the auditability guarantees. |
| **[docs/SCHEMA.md](docs/SCHEMA.md)** | **As-built** schema: the 7 implemented tables, full field reference, ERD, and the Alembic migration plan. |
| **[docs/REGIME_ENGINE.md](docs/REGIME_ENGINE.md)** | Market-regime engine: scoring system, configuration, API, and persistence mapping (implemented). |
| **[docs/SCANNER.md](docs/SCANNER.md)** | Momentum scanner: filters, momentum score, ranking, persistence (implemented). |
| **[docs/ANALYTICS.md](docs/ANALYTICS.md)** | Performance & trade analytics built around the positive-skew objective (implemented). |
| **[docs/BACKTESTING.md](docs/BACKTESTING.md)** | Event-driven backtester: no look-ahead (with proofs), commissions, slippage, gap risk (implemented). |
| **[docs/TRADE_INTELLIGENCE.md](docs/TRADE_INTELLIGENCE.md)** | Trade intelligence DB: per-trade storage, attribution reports, SQL queries, dashboards (implemented). |
| **[docs/RESEARCH_REPORTING.md](docs/RESEARCH_REPORTING.md)** | Automated weekly research reports: evidence only (markdown/JSON/DB), never auto-tunes (implemented). |
| **[docs/INSTRUMENT_SELECTION.md](docs/INSTRUMENT_SELECTION.md)** | Instrument selection engine: shares / calls / spreads / LEAPS from thesis + context (implemented). |
| **[docs/PAPER_SLICE.md](docs/PAPER_SLICE.md)** | Paper trading vertical slice: execution primitives, portfolio/position tracking, trade journal, and the daily pipeline (implemented). |
| **[docs/ORCHESTRATION.md](docs/ORCHESTRATION.md)** | Daily orchestration engine: recover → exits → entries → persist, the `runs` registry, single source of truth & crash recovery (implemented). |
| **[docs/AUDIT_LOGGING.md](docs/AUDIT_LOGGING.md)** | Append-only audit log: immutable, twice-timestamped, queryable, crash-safe records of every material action (implemented). |
| **[docs/E2E_VERIFICATION.md](docs/E2E_VERIFICATION.md)** | End-to-end verification: pass/fail checklist, automated tests, and the manual testing workflow for the full paper path. |
| **[docs/PRODUCTION_READINESS_TESTS.md](docs/PRODUCTION_READINESS_TESTS.md)** | Production-readiness QA plan: startup/corruption/missing-data/scale/memory/crash-recovery tests (manual + automated + failure injection + load) and findings. |
| **[.github/workflows/desktop.yml](.github/workflows/desktop.yml)** | Desktop CI: install → typecheck (fails on any TS error) → build → headless Electron startup validation, on every push/PR. |
| **[.github/workflows/release.yml](.github/workflows/release.yml)** | Release CI/CD: on a `v*` tag, run the quality gate (ruff + mypy + tests + desktop build), build the Windows installer (`build_windows.ps1`), and publish a GitHub Release with `MomentumLab-Setup-*.exe` (+ auto-update metadata). |
| **[docs/DESKTOP_AUDIT.md](docs/DESKTOP_AUDIT.md)** | Desktop app audit: launch/connectivity readiness, per-screen feature completeness (live vs demo vs placeholder), screenshot checklist, and a UAT plan. |
| **[docs/CLI.md](docs/CLI.md)** | The `mrp` CLI: `serve` / `paper-run` / `scan` / `health` / `replay`, logging, and usage examples (implemented). |
| **[docs/UPDATER.md](docs/UPDATER.md)** | Local self-update (`mrp update` / `mrp rollback`): check → backup → pull → migrate → verify → restart, with automatic rollback (implemented). |
| **[docs/SETUP.md](docs/SETUP.md)** | Fresh-machine setup: dependencies, env vars, database + migrations, backend/frontend startup, verification, troubleshooting. |
| **[docs/DEMO_DATA.md](docs/DEMO_DATA.md)** | Demo dataset seeder: 50 trades, 100 signals, snapshots, regimes, 15 ranked scan/conviction/opportunity candidates, risk metrics, optimization results, replay data — every UI screen populated without the scanner. |
| **[docs/WINDOWS_INSTALLER.md](docs/WINDOWS_INSTALLER.md)** | Momentum Lab Windows 11 installer: architecture, one-command build, NSIS packaging, shortcuts, icon, uninstall, startup checklist. |
| **[docs/DATA_PROVIDER_SETTINGS.md](docs/DATA_PROVIDER_SETTINGS.md)** | Editable Settings: pick the market-data provider and enter API keys from the UI (provider → settings.yaml, secrets → .env, never echoed). |
| **[docs/CONVICTION_EXPLAINABILITY.md](docs/CONVICTION_EXPLAINABILITY.md)** | Per-factor conviction explainability: signed contributors (raw · weight · impact vs neutral) + a plain-language narrative, computed at read time from the stored breakdown. |
| **[docs/WATCHLISTS.md](docs/WATCHLISTS.md)** | Multi-horizon watchlists (Today/Week/Month): horizon-reweighted conviction ranking with expected move/risk/RR, persisted history, and over-time comparison. |
| **[docs/WATCHLIST_PERFORMANCE.md](docs/WATCHLIST_PERFORMANCE.md)** | Watchlist performance tracking: forward 1d/1w/1m returns + MFE/MAE per stored entry, scorecards & prediction-quality (conviction/rank IC, calibration, quality score) comparing Daily/Weekly/Monthly — does the advice work? |
| **[docs/TRADE_PLAN.md](docs/TRADE_PLAN.md)** | Read-only trade-plan generation: entry/stop/3 targets/sizing from ATR, support, analogs, volatility & regime, with risk/reward/failure summaries. |
| **[docs/LIFECYCLE.md](docs/LIFECYCLE.md)** | Setup lifecycle tracking: every candidate auto-derived into one state (Building→…→Completed/Failed), persisted with transition history, filterable, refreshed each session. |
| **[docs/COMMAND_CENTER.md](docs/COMMAND_CENTER.md)** | Market Command Center (default landing): regime, top daily/weekly/monthly opportunities, standout setups, portfolio heat, performance, watchlist changes & triggered setups — one aggregate. |
| **[docs/SIGNAL_EVALUATION.md](docs/SIGNAL_EVALUATION.md)** | Signal evaluation: per-signal outcome/MFE/MAE/return tracking + calibration, signal-quality (E-ratio) and conviction-accuracy (AUC/Brier/monotonic) dashboards. |
| **[docs/OPTIONS_ELIGIBILITY.md](docs/OPTIONS_ELIGIBILITY.md)** | Options-eligibility gate: Shares-Preferred vs Leverage-Eligible (0-100 confidence) from liquidity, volatility, expected move, time horizon, spread quality & regime. |
| **[docs/OPTIONS_RECOMMENDATION.md](docs/OPTIONS_RECOMMENDATION.md)** | Options-recommendation engine: for an eligible setup, a defined-risk contract (expiration/strike/delta/risk/max-loss/target/allocation) in the order Deep ITM → ATM → Vertical Spread, avoiding low liquidity, wide spreads, lottery & short-dated; volatility (IV) feed from the scanner (`implied_vol`/`iv_rank`), risk disclosures, no execution. |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Phased implementation order. |

## Tech stack

Python 3.12 · SQLite + SQLAlchemy 2.0 · Pandas · NumPy · Plotly · FastAPI · Pydantic · Typer

## Project layout

```
config/        versioned tunables (strategy + risk), NOT secrets
docs/          architecture & design documents
src/momentum/  the package: core, data, universe, signals, risk, portfolio,
               execution, backtest, analytics, reporting, persistence, api,
               orchestration, cli
tests/         unit / integration / fixtures
notebooks/     exploratory research
scripts/       one-off ops
data/ reports/ logs/   gitignored runtime artifacts
```

## Getting started (once implemented)

```bash
cp .env.example .env                      # add data/broker credentials
cp config/settings.example.yaml config/settings.yaml
cp config/risk.example.yaml     config/risk.yaml
cp config/strategy.example.yaml config/strategy.yaml
cp config/universe.example.yaml config/universe.yaml

make install        # editable install + deps
make backtest       # run a backtest from config  (mrp backtest)
make serve          # FastAPI service              (mrp serve)
```

The intended CLI surface: `mrp ingest | scan | backtest | report | paper-trade | serve`.
