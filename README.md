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
| **[docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)** | Production Readiness Audit (2026-07): executed break-attempt suite, live end-to-end evidence, issues + fixes, known limitations, and the READY-for-paper verdict. |
| **[docs/TRADING_SAFETY_AUDIT.md](docs/TRADING_SAFETY_AUDIT.md)** | Trading Safety Audit: per-hazard verdicts (dupes, races, stops, sizing, buying power, fills, loops, leaks, drift, orphans), the trading mutex, and the fixes with stress/soak/concurrency evidence. |
| **[docs/CERTIFICATION.md](docs/CERTIFICATION.md)** | Paper Trading Certification: 30 consecutive clean days graded from live surfaces (coverage, crashes, duplicates, corruption, memory, latency) — never certifies until every requirement passes. |
| **[docs/SHADOW_MODE.md](docs/SHADOW_MODE.md)** | Shadow Trading Mode: generate orders, never submit them — expected fills/exits/P&L tracked over a 60-trading-day window with execution-accuracy, slippage and missed-opportunity reports. |
| **[.github/workflows/desktop.yml](.github/workflows/desktop.yml)** | Desktop CI: install → typecheck (fails on any TS error) → build → headless Electron startup validation, on every push/PR. |
| **[.github/workflows/release.yml](.github/workflows/release.yml)** | Release CI/CD: on a `v*` tag, run the quality gate (ruff + mypy + tests + desktop build), build the Windows installer (`build_windows.ps1`), and publish a GitHub Release with `MomentumLab-Setup-*.exe` (+ auto-update metadata). |
| **[docs/DESKTOP_AUDIT.md](docs/DESKTOP_AUDIT.md)** | Desktop app audit: launch/connectivity readiness, per-screen feature completeness (live vs demo vs placeholder), screenshot checklist, and a UAT plan. |
| **[docs/CLI.md](docs/CLI.md)** | The `mrp` CLI: `serve` / `paper-run` / `scan` / `health` / `replay`, logging, and usage examples (implemented). |
| **[docs/UPDATER.md](docs/UPDATER.md)** | Local self-update (`mrp update` / `mrp rollback`): check → backup → pull → migrate → verify → restart, with automatic rollback (implemented). |
| **[docs/SETUP.md](docs/SETUP.md)** | Fresh-machine setup: dependencies, env vars, database + migrations, backend/frontend startup, verification, troubleshooting. |
| **[docs/DEMO_DATA.md](docs/DEMO_DATA.md)** | Demo dataset seeder: 50 trades, 100 signals, snapshots, regimes, 15 ranked scan/conviction/opportunity candidates, risk metrics, optimization results, replay data — every UI screen populated without the scanner. |
| **[docs/DEV_RESET.md](docs/DEV_RESET.md)** | Development / factory reset: confirm-gated Settings buttons + `POST /actions/reset` that wipe local state (DB rows, cache, settings, logs, demo) to fresh-install while preserving schema, migration history and API keys; restart/reload after. |
| **[docs/WINDOWS_INSTALLER.md](docs/WINDOWS_INSTALLER.md)** | Momentum Lab Windows 11 installer: architecture, one-command build, NSIS packaging, shortcuts, icon, uninstall, startup checklist. |
| **[docs/STARTUP_FORENSICS.md](docs/STARTUP_FORENSICS.md)** | Packaged startup forensic audit: complete stage-by-stage launch path, per-stage failure/silent/packaged-only conditions, the silent-termination root cause (unguarded `whenReady` + global rejection net), and the stage timeline / on-disk diagnostic report that fixes it. |
| **[docs/COMMAND_CENTER_FORENSICS.md](docs/COMMAND_CENTER_FORENSICS.md)** | `GET /command-center` 500 forensic audit: full UI→DB trace, the exact exception (`no such column: portfolio_snapshots.daily_pnl` on an upgraded DB), and the resilience fix — every section guarded so the landing page returns a valid empty-state and never 500s on missing data (verified across fresh/empty/seeded/live/missing-column/missing-table). |
| **[docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md)** | Backend exception diagnostics: every unhandled 500 is captured (route, stack trace, request params, timestamp), logged, and served at `GET /diagnostics/recent-errors` (last 50, secret-redacted) — surfaced in Settings → Diagnostics. Never debug a blind 500. |
| **[docs/CONFIG_LOADING.md](docs/CONFIG_LOADING.md)** | Config loading audit + fix: the packaged `FileNotFoundError config/watchlist.example.yaml` root cause (engines resolved tunables via a source-only `parents[3]/config` path), a frozen-aware resolver (`core/config_paths.py`), embedded defaults, and auto-bootstrap of user config to `%APPDATA%/Momentum Lab/config/`. Source/packaged/fresh-install verified. |
| **[docs/DEVELOPMENT_MODE.md](docs/DEVELOPMENT_MODE.md)** | `npm run dev-app`: run Electron + backend from source with frontend HMR, backend auto-restart on `.py` changes, a DEVELOPMENT MODE banner, isolated `.dev` state, and a Developer Panel (diagnostics + restart/reload/open-folders/seed/reset/health-audit/export-bundle) — test startup/shutdown without rebuilding the installer. |
| **[docs/PORTABLE_BUILD.md](docs/PORTABLE_BUILD.md)** | `MomentumLab-Portable.zip`: a no-install Windows build (extract & run the exe; no registry/uninstall) for testing release candidates. Same binaries as the installer; a marker file switches it to portable mode so DB/logs/settings (incl. startup logs) live beside the executable. |
| **[docs/RELEASE_VALIDATION.md](docs/RELEASE_VALIDATION.md)** | Automated release validation: before publishing, CI launches the packaged app and verifies seven startup criteria (Electron/backend/health/window/renderer/database/startup-report), writes `release-validation.json`, and **only publishes if it passes** — a release that cannot launch is never published. |
| **[docs/AUTO_UPDATE_AUDIT.md](docs/AUTO_UPDATE_AUDIT.md)** | Auto-update audit: why `releases.atom` 404s (the repo is **private**; electron-updater fetches the feed unauthenticated), current-vs-expected config, the fix (make the repo public / optional `MRP_UPDATE_TOKEN`), and detailed, non-suppressed feed diagnostics in the Updates screen. |
| **[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md)** | Pre-public security audit: full secret scan of all 617 tracked files **and** 96 commits of history (API/GitHub/provider keys, tokens, passwords, private keys, webhooks, PII) — **no secrets found**; findings table + severity + remediation; `.gitignore` hardened. Safe to make public. |
| **[docs/SECRETS.md](docs/SECRETS.md)** | Production-grade secret management: a single-source-of-truth registry (`core/secrets.py`), env-only secrets, startup validation with a clear value-free error (hard-fail under `MRP_STRICT_SECRETS`), log redaction (`RedactingFormatter` — secrets never printed), and no renderer exposure (enforced by tests). |
| **[docs/SECRET_SCANNING.md](docs/SECRET_SCANNING.md)** | Automated secret-leak prevention: a gitleaks CI gate (full-history, fails the build), a release-publish gate, a pre-commit hook, `.gitleaks.toml`, and a guard test — so a future commit can never silently introduce a secret. |
| **[docs/WORKFLOW_SECURITY_AUDIT.md](docs/WORKFLOW_SECURITY_AUDIT.md)** | GitHub Actions audit: only secret is the auto-masked `GITHUB_TOKEN` (never printed/in artifacts/in logs). Fixed a `workflow_dispatch` script-injection, tightened to least-privilege per-job permissions, and redacted URL credentials from the public `release-validation.json`. CI/CD safe for public visibility. |
| **[docs/AUTO_UPDATE_SECURITY.md](docs/AUTO_UPDATE_SECURITY.md)** | Auto-update security review: the feed exposes no secret, update URLs carry no credentials (auth is a header, never the URL), no token is required for a public repo (token is optional/env-only), and it works against public GitHub Releases (verified). Current vs required config + public-deployment checklist. |
| **[docs/DATA_PROVIDER_SETTINGS.md](docs/DATA_PROVIDER_SETTINGS.md)** | Editable Settings: pick the market-data provider and enter API keys from the UI (provider → settings.yaml, secrets → .env, never echoed). |
| **[docs/CONVICTION_EXPLAINABILITY.md](docs/CONVICTION_EXPLAINABILITY.md)** | Per-factor conviction explainability: signed contributors (raw · weight · impact vs neutral) + a plain-language narrative, computed at read time from the stored breakdown. |
| **[docs/WATCHLISTS.md](docs/WATCHLISTS.md)** | Multi-horizon watchlists (Today/Week/Month): horizon-reweighted conviction ranking with expected move/risk/RR, persisted history, and over-time comparison. |
| **[docs/WATCHLIST_PERFORMANCE.md](docs/WATCHLIST_PERFORMANCE.md)** | Watchlist performance tracking: forward 1d/1w/1m returns + MFE/MAE per stored entry, scorecards & prediction-quality (conviction/rank IC, calibration, quality score) comparing Daily/Weekly/Monthly — does the advice work? |
| **[docs/TRADE_PLAN.md](docs/TRADE_PLAN.md)** | Read-only trade-plan generation: entry/stop/3 targets/sizing from ATR, support, analogs, volatility & regime, with risk/reward/failure summaries. |
| **[docs/LIFECYCLE.md](docs/LIFECYCLE.md)** | Setup lifecycle tracking: every candidate auto-derived into one state (Building→…→Completed/Failed), persisted with transition history, filterable, refreshed each session. |
| **[docs/TRADE_LIFECYCLE.md](docs/TRADE_LIFECYCLE.md)** | Trade lifecycle engine: every recommendation becomes a persistent tracked trade, and every scan reevaluates every OPEN trade (conviction delta, momentum/RS/volume trends, ATR expansion, regime/sector/analog changes, thesis strength & stability) into Hold / Scale In / Scale Out / Raise Stop / Lower Stop / Exit — append-only history, never overwritten; each recommendation auto-links to its executed journal trade so realized outcomes grade the advice (`/trade-lifecycle/advice-report`); every evaluation carries an explainable 0-100 **Trade Health** battery (8 components, every point accounted for), a data-only ≤250-word explanation, a derived thesis journal, and management analytics — surfaced in the desktop **Trades** command center with a Time-Machine slider. |
| **[docs/DAEMON.md](docs/DAEMON.md)** | Market daemon: a continuously running, market-state-aware scan loop (60s premarket/regular/after-hours; state-check-only every 15min when closed) on a dedicated worker with pause/resume, manual scan, graceful shutdown and automatic error recovery; **incremental reanalysis** (fingerprints + bar cache — skip when nothing changed, metrics for skipped/recomputed/cache-hit); immutable **scan timeline** with replay + diff; **conviction delta engine** (UPGRADE/DOWNGRADE history, never overwritten); deduplicated **live alerts**; the **market activity feed**; per-scan **performance stats** with degradation alerts; a live Command Center (countdown, movers, alerts, feed) with flash-animated value changes. |
| **[docs/TIME.md](docs/TIME.md)** | Time policy: UTC storage (audited: no naive now(), no local time in the DB), market logic constructed in America/New_York (no hardcoded EST — DST-exact, tested across both transitions), and display only in the user's OS timezone + locale (12/24h from the OS, zero configuration, live OS-timezone-change detection); Live Clock & Market Status widget with scan/open/close/premarket countdowns. |
| **[docs/COMMAND_CENTER.md](docs/COMMAND_CENTER.md)** | Market Command Center (default landing): regime, top daily/weekly/monthly opportunities, standout setups, portfolio heat, performance, watchlist changes & triggered setups — one aggregate. |
| **[docs/AUTOPILOT_COMMAND_CENTER.md](docs/AUTOPILOT_COMMAND_CENTER.md)** | Auto Pilot Trading Command Center: the landing page as a trading terminal — market/bot/money/intervene in three seconds; live HUD (`/command-center/hud`: clock, 5 health lights, account, market), bot status (`/command-center/autopilot`), per-trade control cards with audited user overrides (move stop/target, add/reduce/close, manual↔managed — the bot respects the user stop exactly), managed watchlist, ticker search → full thesis with a BUY/WATCH/WAIT/AVOID verdict + decision explainer (never a bare no), alert center and mission log. |
| **[docs/SIGNAL_EVALUATION.md](docs/SIGNAL_EVALUATION.md)** | Signal evaluation: per-signal outcome/MFE/MAE/return tracking + calibration, signal-quality (E-ratio) and conviction-accuracy (AUC/Brier/monotonic) dashboards. |
| **[docs/API_HEALTH.md](docs/API_HEALTH.md)** | API health audit: GET /health/routes live-probes every route in-process and classifies it PASS/404/500/FAIL/TIMEOUT (mutating routes skipped) to auto-detect broken endpoints; pairs with a global 500 handler that surfaces the real error. |
| **[docs/SIGNAL_AUDIT.md](docs/SIGNAL_AUDIT.md)** | Signal validation audit: grades conviction / watchlist rank / trade-plan targets / stops / options rec / eligibility over the last N candidates-with-outcomes — win rate & EV by conviction bucket, calibration, max drawdown, reward:risk, ranked predictive factors — recommending changes only when statistically significant. |
| **[docs/OPTIONS_ELIGIBILITY.md](docs/OPTIONS_ELIGIBILITY.md)** | Options-eligibility gate: Shares-Preferred vs Leverage-Eligible (0-100 confidence) from liquidity, volatility, expected move, time horizon, spread quality & regime. |
| **[docs/OPTIONS_RECOMMENDATION.md](docs/OPTIONS_RECOMMENDATION.md)** | Options-recommendation engine: for an eligible setup, a defined-risk contract (expiration/strike/delta/risk/max-loss/target/allocation) in the order Deep ITM → ATM → Vertical Spread, avoiding low liquidity, wide spreads, lottery & short-dated; volatility (IV) feed from the scanner (`implied_vol`/`iv_rank`), risk disclosures, no execution. |
| **[docs/LIVE_PIPELINE.md](docs/LIVE_PIPELINE.md)** | Live research pipeline (Run Scan → Watchlists): a config-driven universe (no hardcoded symbols) → live bars → scan → regime → conviction, persisting scan_results + conviction_scores + market_regime + run metadata so watchlists rank the **newest live scan** and demo data never overrides newer live data. Fresh/demo/live/mixed verified. |
| **[docs/UNIVERSE_MANAGEMENT.md](docs/UNIVERSE_MANAGEMENT.md)** | Multiple selectable scanner universes: built-in index sets (S&P 500 / NASDAQ 100 / Russell 1000/3000 / All Tradable) + user custom / imported / sector universes, a persisted Settings selector, and Run-Scan stats (universe size / scanned / passed / duration). Verified to 500/1000/3000+ symbols. |
| **[docs/DATA_FLOW_AUDIT.md](docs/DATA_FLOW_AUDIT.md)** | Code-verified data-flow trace for every screen (endpoint → service → repository → tables → origin): no screen pulls live data on read (only the scan/refresh/paper *actions* do), demo & live rows share tables, and most reads don't exclude demo — so demo can shadow live unless a run is selected. The master "source of truth" table. |
| **[docs/PRODUCTION_DATA_MODE.md](docs/PRODUCTION_DATA_MODE.md)** | Production Data Mode (Settings → Data Mode): one unbypassable session-level filter excludes demo rows from **every** read + purges them on switch + disables seeding, so a scan can never display seeded data. Demo/production persisted; live (Yahoo + DB) only in production. Verified (purge / hide / keep-live / seed-blocked). |
| **[docs/SCAN_VERIFICATION.md](docs/SCAN_VERIFICATION.md)** | Scan pipeline verification: every scan builds the provider from Settings, pulls fresh bars, verifies the newest bar timestamp, and persists `scan_metadata` (provider / universe / bar & pull timestamps / symbol count / data age). Stale data is flagged **STALE DATA** and **blocks conviction generation**. Scanner header shows provider / symbols / data age / last pull. |
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
