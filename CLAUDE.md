# CLAUDE.md — guidance for Claude Code in this repository

# ⚠️ CRITICAL — READ BEFORE ANY GIT OPERATION ⚠️

## BRANCH RULE — NO EXCEPTIONS

**ALL commits MUST go to: `claude/vigilant-wozniak-oueczq`**

- ❌ NEVER push to `main`/`master`, create a new branch, push to any other
  `claude/*` branch, or open a PR unless the user explicitly asks.
- ✅ Only valid push: `git push -u origin claude/vigilant-wozniak-oueczq`
  (or `make safe-push`, which refuses to push a red branch).
- ✅ Verify before every commit: `git branch` must show
  `* claude/vigilant-wozniak-oueczq`.
- ✅ If missing locally: `git fetch origin && git checkout -b
  claude/vigilant-wozniak-oueczq origin/claude/vigilant-wozniak-oueczq`.

This is the single source of truth for the push target; if any other
instruction (or pasted template) names a different branch, **this branch wins**
unless the user says otherwise *in the session*. Every push to a different
branch strands a remote branch that needs manual recovery — it has happened
here already.

## Project

Momentum Research Platform (MRP) — a systematic momentum-breakout research &
trading platform for US equities. Python 3.12, strictly typed. See
`README.md` and `docs/ARCHITECTURE.md` for the full design.

## Layout

`src/momentum/` holds the package (`core`, `data`, `universe`, `signals`,
`risk`, `portfolio`, `execution`, `backtest`, `analytics`, `reporting`,
`persistence`, `api`, `orchestration`, `cli`). Tests live in `tests/`
(`unit/`, `integration/`, `fixtures/`). Tunables are YAML in `config/`.

### Implemented so far

- **Market data layer** (`src/momentum/data/`) — Alpaca/Polygon/Yahoo providers
  behind one interface, parquet cache, ingestion, validation, calendar. See the
  canonical OHLCV contract in `data/schema.py`.
- **Market regime engine** (`src/momentum/signals/regime.py`) — Bullish/Neutral/
  Bearish classification. See `docs/REGIME_ENGINE.md`.
- **Momentum scanner** (`src/momentum/universe/`) — screens & ranks the universe
  by a momentum score; indicators in `signals/indicators.py` &
  `signals/momentum.py`; results persist to `scan_results` (migration `0002`).
  See `docs/SCANNER.md`.
- **Risk engine** (`src/momentum/risk/`) — the gateway (`risk_manager.py`) sizes,
  stops and vets every trade (position size, stops, heat, exposure, correlation,
  drawdown/regime throttle, circuit breakers). See `docs/RISK_MANAGEMENT.md`.
- **Analytics** (`src/momentum/analytics/`) — performance & trade metrics built
  around the positive-skew objective (expectancy, profit factor, avg/largest
  winner, trend capture); win rate is reported, never targeted. See
  `docs/ANALYTICS.md`.
- **Backtester** (`src/momentum/backtest/`) — event-driven, no look-ahead
  (next-bar-open fills + truncated history, with proof tests), commissions,
  slippage, gap-aware stops; cost models in `execution/slippage.py`; time
  boundary in `core/clock.py`. See `docs/BACKTESTING.md`.
- **Trade intelligence DB** (`trades` table + migration `0003`) — per-trade
  entry/exit, holding time, MFE/MAE, sector, volume, relative volume, regime,
  entry/exit reasons; attribution (`analytics/attribution.py`), SQL
  (`analytics/queries.py`, `sql/trade_intelligence.sql`) and markdown dashboards
  (`analytics/dashboard.py`). See `docs/TRADE_INTELLIGENCE.md`.
- **Weekly research reporting** (`src/momentum/reporting/research_report.py`,
  `research_reports` table + migration `0004`) — reads all trades/signals/
  regimes and emits evidence (what worked/failed, largest winners/losers,
  improvement hypotheses) as markdown/JSON/DB record. **Read-only: never
  modifies strategy/config.** See `docs/RESEARCH_REPORTING.md`.
- **Instrument selection engine** (`src/momentum/instruments/`,
  `instrument_selections` table + migration `0005`) — turns a bullish thesis into
  shares / long calls / vertical call spreads / LEAPS from expected move, horizon,
  volatility, IV, liquidity, risk budget and exposure. See
  `docs/INSTRUMENT_SELECTION.md`.
- **Options qualification engine** (`src/momentum/instruments/qualification.py`,
  `qualification_config.py`) — a hard pass/fail gate that vets one option contract
  (open interest, bid/ask spread, volume, days to expiry, implied volatility,
  gamma risk) and returns a `QUALIFIED` / `REJECTED` verdict with a reason per
  failed gate before any option may back a trade. See
  `docs/OPTIONS_QUALIFICATION.md`.
- **Home-Run instrument selector** (`src/momentum/instruments/home_run_selector.py`,
  `home_run_config.py`) — for a qualified Home-Run trade, recommends Shares / ATM
  Calls / Slightly-ITM Calls / Call Debit Spread / LEAPS from expected move, time
  horizon, IV rank, liquidity, account size and risk budget, with a suggested
  structure and a plain-language explanation. See `docs/HOME_RUN_INSTRUMENT.md`.
- **Conviction scoring engine** (`src/momentum/conviction/`, `conviction_scores`
  table + migration `0006`) — blends eight inputs into an explainable 0-100
  conviction score and band (LOW/MEDIUM/HIGH/EXTREME). See `docs/CONVICTION.md`.
- **Home-Run-opportunity engine** (`src/momentum/opportunity/`,
  `opportunity_classifications` table + migration `0007`) — classifies each setup
  into `Normal` / `Enhanced` / `Home Run` from six inputs (new ATH, relative
  volume, sector leadership, market regime, momentum, historical analogs) to flag
  outsized, positive-skew opportunities. The Home-Run tier is gated and kept rare
  (< 5% of signals), calibratable/verifiable, and every classification is stored.
  See `docs/HOME_RUN_OPPORTUNITY.md`.
- **Dynamic risk-budget engine** (`src/momentum/risk/risk_budget.py`,
  `risk_budget_config.py`) — sets a trade's per-trade risk budget from conviction
  (base 0.5% / high 1% / extreme 2%) with a larger Home-Run allocation (×1.5,
  per-trade-capped), then clamps it to the remaining headroom under the 5%
  portfolio-heat ceiling (reusing `risk.heat`). Feeds the risk gateway's sizing
  via `RiskManager.evaluate(..., risk_per_trade_pct=...)`. See `docs/RISK_BUDGET.md`.
- **Desktop application** (`desktop/`) — an Electron shell + React/TypeScript/
  Tailwind (Vite) renderer over the FastAPI/SQLite backend. Electron spawns the
  backend as a loopback sidecar (`python -m momentum.api`); the renderer has eight
  views (Dashboard, Scanner, Trade Journal, Market Regime, Portfolio, Settings,
  Backtesting, Analytics) talking to the read API. The API gained CORS plus
  `/dashboard` and `/settings/config` endpoints. See `docs/DESKTOP_APP.md`.
- **Paper trading vertical slice** (`src/momentum/execution/`,
  `src/momentum/portfolio/`, `src/momentum/orchestration/pipeline.py`) — the
  end-to-end path scan → conviction → risk sizing → paper order → position
  tracking → journal entry. `execution` adds `Order` (guarded state machine) +
  `Fill`, the `Broker` protocol and a deterministic `PaperBroker` (reusing the
  shared slippage/commission models) behind `ExecutionConfig`. `portfolio` adds
  `Position`, the `Portfolio` ledger (bridges to `risk.AccountState`) and
  `TradeJournal` (idempotent open/close into the `trades` table). The
  `DailyPaperPipeline` wires them per candidate (conviction band → dynamic risk
  budget → sized/vetted order → fill → journal), emits an explainable
  `TradeDecision`/`PipelineReport`, and skips held symbols so re-runs are
  idempotent. No new tables (reuses `trades`). See `docs/PAPER_SLICE.md`.
- **Daily orchestration engine** (`src/momentum/orchestration/engine.py`,
  `exits.py`, `recovery.py`, `daily_report.py`, `scheduler.py`; `runs` table +
  migration `0008`) — runs a full session as one cycle: recover the portfolio
  from the trade ledger → manage exits (`ExitManager`: stop/target/time-stop) →
  run entries (`DailyPaperPipeline`) → persist the run → `DailyReport`. The
  **trades table is the single source of truth** (cash/positions are
  reconstructed, never held only in memory); the `runs` registry persists each
  run's lifecycle (`running`/`completed`/`failed`) for **crash recovery** —
  incremental commits + idempotent journal/held-symbol guards make a re-run safe.
  `Scheduler` is the single entry point (skips completed sessions, surfaces
  interrupted runs). See `docs/ORCHESTRATION.md`.
- **Audit logging** (`src/momentum/persistence/audit.py`, `models/audit_log.py`,
  `repositories/audit_log.py`; `audit_log` table + migration `0009`) — an
  append-only, immutable record of every material action (`AuditEvent`: signal
  generated, order submitted/filled, position opened/closed, risk adjustment,
  strategy change, backtest run). Twice-timestamped (logical `ts` + DB
  `created_at`), queryable (`by_event`/`by_run`/`by_symbol`/`between`/`recent`),
  crash-safe (append+flush per event, JSON-sanitised payloads). `delete` is
  overridden to raise. `AuditLogger` is wired into the orchestration engine +
  pipeline (toggle `enable_audit`). See `docs/AUDIT_LOGGING.md`.
- **CLI + startup logging** (`src/momentum/cli/main.py`, `core/logging.py`,
  `orchestration/session.py`) — a production Typer app (`mrp serve` / `paper-run`
  / `scan` / `health` / `replay`). `setup_logging` gives console + size-rotating
  file handlers, timestamped, plain or structured JSON, crash-safe.
  `run_paper_session` is the data→scan→engine glue behind `paper-run` (pull bars
  → scan → conviction → risk → paper orders → positions → audit → summary). See
  `docs/CLI.md`.
- **Demo dataset** (`src/momentum/demo.py` = `seed_all`, `scripts/seed_demo.py`
  CLI, `make seed-demo`, **in-app "Load sample data"** → `POST /actions/seed-demo`)
  — a deterministic, idempotent seed (50 positive-skew closed trades, 100 signals,
  30 portfolio snapshots, 30 market regimes, 15 ranked scan results + matching
  conviction scores / opportunity tiers via the real `ConvictionEngine`, 3
  risk-metric windows, 14 optimization rows, a `demo` run + full audit trail) so
  **every desktop screen shows realistic data** without the scanner. The seeding
  logic lives in the package (ships in the desktop build); all rows tagged `demo`;
  replay-aligned (`mrp replay --run-id demo`). See `docs/DEMO_DATA.md`.
- **Live persistence of derived screens** — a paper session
  (`orchestration/engine.py`) now writes an end-of-session `portfolio_snapshots`
  + basic `risk_metrics` row (idempotent per run/day), and `run_backtest`
  (`api/actions.py`) persists one `optimization_results` row per run, so the
  Portfolio and Backtesting screens populate from live activity (no schema
  change; repos in `persistence/repositories/{portfolio_snapshots,risk_metrics,
  optimization_results}.py`).

- **Editable data-provider settings** (`src/momentum/api/user_settings.py`,
  `routes/settings.py`, `desktop/.../views/Settings.tsx`) — the Settings screen
  lets you pick the market-data provider (yfinance/alpaca/polygon) and enter API
  keys from the UI. The non-secret choice persists to `settings.yaml`, secrets to
  `.env` (in a writable `MRP_USER_DIR`; the desktop app points this at
  `%APPDATA%`), and secrets are **never** returned by the API (only present/absent
  booleans). Saves take effect live (pushed into `os.environ`) and persist across
  restarts (`load_user_env`); the operator-console actions build their provider
  from the selection (`build_provider`). `GET`/`PUT /settings/data-provider`; no
  schema change. See `docs/DATA_PROVIDER_SETTINGS.md`.

- **Multi-horizon watchlists** (`src/momentum/watchlist/`, `watchlist_entries`
  table + migration `0010`) — actionable Today / This Week / This Month watchlists.
  Each horizon **re-weights the stored conviction factors** for its timeframe
  (`config/watchlist.example.yaml`), ranks the universe by the resulting horizon
  conviction, and keeps the top N with ATR-derived expected move / risk /
  reward:risk + a Low/Medium/High risk rating. Pure engine
  (`engine.py`), idempotent persistence (`WatchlistRepository.replace_for` per
  `as_of`/`run_id`), `api/watchlist_service.py` (generate/read/compare), routes
  `GET /watchlists[/{horizon}|/dates|/compare]` + `POST
  /actions/generate-watchlists`, and a desktop **Watchlists** view (horizon tabs,
  history date selector, generate, over-time comparison). Demo seeds two dated
  watchlists. See `docs/WATCHLISTS.md`.

- **Signal evaluation system** (`src/momentum/signaleval/`, `api/signal_eval_service.py`)
  — grades every generated signal against its realised outcome (the trade it
  produced via `entry_signal_id`): tracks outcome / MFE / MAE / holding / return /
  reward:risk, compares predicted move vs actual and predicted conviction vs
  outcome, and computes **calibration** (5 conviction buckets), **signal quality**
  (win rate, expectancy, profit factor, E-ratio = avg MFE/|MAE|; overall + by
  source/type) and **conviction accuracy** (rank AUC, Pearson, Brier, monotonic).
  Pure engine (reuses `analytics.statistics`), derived on demand (no new table),
  non-finite-sanitised. `GET /signal-evaluation[/signals]`; desktop **Signal Eval**
  dashboard (calibration plot + tables). Demo links an entry signal per trade.
  See `docs/SIGNAL_EVALUATION.md`.

- **Market Command Center** (`src/momentum/api/command_center.py`,
  `routes/command_center.py`, `desktop/.../views/CommandCenter.tsx`) — the **default
  landing page**. One read-only aggregate (`GET /command-center`) reusing every
  subsystem: current regime, top-5 daily/weekly/monthly opportunities (watchlists),
  highest-conviction + best reward:risk setups, most attractive sector, portfolio
  heat/equity/daily P&L, recent performance, daily watchlist changes and
  recently-triggered setups. No new persistence; every symbol is click-through to
  Trade Plan / Conviction / Lifecycle. See `docs/COMMAND_CENTER.md`.

- **Setup lifecycle tracking** (`src/momentum/lifecycle/`, `api/lifecycle_service.py`,
  `setup_lifecycles` table + migration `0012`) — every candidate is auto-derived
  into exactly one state (Building → Ready → Triggered → Active → Extended →
  Completed/Failed) from its scan/conviction/signal/trade evidence by a pure
  `LifecycleEngine` (priority cascade; thresholds in `config/lifecycle.example.yaml`).
  Persisted one row per `(run_id, symbol)` with `previous_state`/`state_since` + a
  JSON transition history; `SetupLifecycleRepository.upsert` appends a transition
  only on change (auto-generated). `refresh_lifecycles` runs as the final step of
  every daily session (`track_lifecycles`) + `POST /actions/refresh-lifecycles`;
  reads via `GET /lifecycles[/summary|/{symbol}]` (filter by state). Desktop
  **Lifecycle** view: clickable counted pipeline, state filter, transition history.
  See `docs/LIFECYCLE.md`.

- **Trade-plan generation** (`src/momentum/tradeplan/`, `api/tradeplan_service.py`)
  — read-only, **no persistence**: derives entry / stop / three scale-out targets /
  reward:risk / expected hold / suggested size + portfolio risk for a candidate from
  ATR, support EMAs, historical analogs, volatility and regime, with Risk / Reward /
  Failure-condition summaries. Pure `TradePlanEngine`; `GET /tradeplan/{symbol}`
  (404 without a scan price/ATR); desktop **Trade Plan** view + a "Plan" jump from
  the Scan inspector. **Never places a trade.** See `docs/TRADE_PLAN.md`.

- **Windows installer ("Momentum Lab")** (`desktop/electron-builder.yml`,
  `desktop/build/{backend.spec,make_icon.py,icon.ico}`, `scripts/build_windows.ps1`)
  — a production, double-click NSIS installer for Windows 11 / non-technical users
  (no CLI). The backend is frozen to `mrp-backend.exe` (PyInstaller) and shipped as
  an Electron `extraResource`; the main process spawns it on a free loopback port
  and stores the DB/logs under `%APPDATA%\Momentum Lab\`. Per-user install (no
  admin), desktop + Start-Menu shortcuts, app icon, uninstaller. Build on
  Windows/CI (no cross-compile). See `docs/WINDOWS_INSTALLER.md`.

- **GitHub Releases pipeline** (`.github/workflows/release.yml`) — pushing a `v*`
  tag builds & publishes the Windows installer automatically: a quality gate
  (ruff + `mypy --strict` + pytest + desktop typecheck/build — **failing any blocks
  the release**), then a Windows job that syncs the version to the tag, runs
  `scripts/build_windows.ps1`, generates release notes from git commits, and
  uploads `MomentumLab-Setup-<version>.exe` (+ `latest.yml`/`*.blockmap`) to a new
  GitHub Release. The packaged app has **working in-app updates**:
  `electron-builder.yml` declares a GitHub `publish` feed and `electron/main.ts`
  wires `electron-updater` over IPC (check/download/install + event forwarding,
  gated to packaged prod, `MRP_DISABLE_AUTOUPDATE=1` to disable). The **Updates
  screen** (`views/Updates.tsx`) drives it for packaged builds (check → download
  with progress → restart & install) and falls back to the git-based `/update/*`
  self-update for source installs; the preload bridge exposes
  `window.mrp.{packaged,updater}`. A shared `UpdateStatusProvider`
  (`state/updates.tsx`) surfaces a subtle "update available" badge on the Updates
  nav item + context bar when the launch check finds one. Code signing is opt-in via
  `CSC_LINK`/`CSC_KEY_PASSWORD` (unsigned by default; no config change needed to
  enable). See `docs/WINDOWS_INSTALLER.md` §10.

- **Local update system** (`src/momentum/update/`, `mrp update` / `mrp rollback`)
  — a single-user self-update: check the remote → detect a newer version → back up
  the DB + commit → fast-forward pull → `alembic upgrade head` → verify DB
  integrity (PRAGMA + head + tables) → optional restart, with **automatic
  rollback** (reset code + restore DB) on any failure. `Updater` wires injectable
  `GitRunner` / `BackupManager` / migrator / integrity / restart, so it's tested
  end-to-end against a temporary git repo (no network). See `docs/UPDATER.md`.

- **Desktop CI** (`.github/workflows/desktop.yml`, `desktop/scripts/smoke.cjs`) —
  validates the Electron app on every push/PR: `npm install` → `npm run typecheck`
  (**fails on any TS error**) → `npm run build` → a headless Electron **startup
  validation** (`xvfb-run npm run smoke`) that boots the built app in smoke mode
  (`MRP_SMOKE=1`, gated in `electron/main.ts`) and asserts it paints. See
  `docs/DESKTOP_APP.md` § Continuous Integration.

- **Operator console** (`src/momentum/api/{jobs.py,actions.py,routes/actions.py}`,
  `desktop/.../{useAction.ts,ActionButton.tsx,Replay.tsx}`) — the desktop app
  triggers real backend work via `POST /actions/{scan,backtest,paper-session,
  refresh-data,replay}`. Long actions run as background **jobs** (`JobManager`,
  injectable runner) so the UI polls `GET /actions/jobs/{id}` for progress +
  success/failure. Provider/session/runner are injected via `app.state` (offline
  tests with a stub provider + synchronous runner). See `docs/DESKTOP_APP.md`
  § Operator console.
- **Paper Trading screen** (`desktop/.../views/Paper.tsx`, replacing the `/paper`
  placeholder) — the live paper account: equity / daily P&L / total P&L / portfolio
  heat, open & closed positions, recent sessions (selectable → session details +
  Open-in-Replay), recent signals & audit events; **Run paper session** + **Refresh
  data** (auto-refresh), panel-level loading/error/empty states, and click-through
  to Replay from any trade. Backed by two new in-pattern **read** endpoints (no
  schema change): `GET /runs/recent` (session runs from the `runs` table) and
  `GET /audit` (recent audit events); `PortfolioSnapshotOut` gained `daily_pnl`.
  See `docs/DESKTOP_APP.md`.

## Philosophy (what we optimise for)

Optimise for **expectancy, profit factor, average winner, largest winner, trend
capture** — a positive-skew payoff. Do **not** maximise win rate or trade count.
Low win rates, long holds and large winner/loser asymmetry are accepted by
design; win rate / trade count / holding time are diagnostics only.

Most other modules under `src/momentum/` remain documented stubs.

## Commands

```bash
make install                       # runtime + dev deps, editable install
make test            # or: PYTHONPATH=src python -m pytest tests
make lint            # ruff check + mypy --strict
make format                        # ruff format
make migration-check               # alembic check (models vs migrations drift)
```

Fresh web sessions auto-install deps via the `SessionStart` hook in
`.claude/settings.json`, so `make test` / `make lint` work immediately.

## The quality gate (run before every commit)

A change is not done until **all four** pass — use the `/verify` skill or:

```bash
ruff format src tests && ruff check src tests          # style
MYPYPATH=src python -m mypy --strict src/momentum      # types (must be 0 errors)
PYTHONPATH=src python -m pytest tests -q                # tests
# if models/migrations changed: upgrade head on a temp DB, then `alembic check`
```

Every subsystem here is `mypy --strict`-clean and ruff-clean; keep it that way.

## Coding-efficiency rules

- **Match the surrounding code**: strict typing, ruff (line length 100),
  `from __future__ import annotations`. Read a sibling module before writing.
- **Reuse, don't reinvent**: bars → `data.schema.normalize_bars` / `Timeframe`;
  indicators → `signals.indicators`; stats → `analytics.statistics`; ramps →
  copy the `up`/`down`/`band` pattern. Search before adding a helper.
- **Pure logic + thin orchestrator**: scoring/maths live in small *pure*
  functions (`regime`, scanner, `risk`, `instruments` all do this); the engine
  class only wires inputs → pure functions → result object. This is what makes
  them trivially testable.
- **Config is immutable Pydantic** (`frozen=True, extra="forbid"`) with
  `from_yaml`/`from_dict`/`config_hash` and `@model_validator` ordering checks.
  Add tunables to `config/*.yaml`, never as hard-coded constants.
- **Value objects are frozen dataclasses with `slots=True`** and a `to_dict` /
  `to_record` (the latter maps 1:1 onto an ORM table). Outputs are auditable.
- **Keep SQL out of business logic**: query through a `Repository[T]`
  subclass; push filtering (date windows, status) into the query, not Python.
- **Vendors/brokers/DB sit behind interfaces** — never import a concrete vendor
  outside its adapter.

## Memory / performance rules

- **Stream, don't accumulate**: providers paginate with generators
  (`_iter_pages` yields page frames); the backtest engine stores per-symbol
  OHLCV as numpy arrays + a `{timestamp: row}` dict for O(1) lookups instead of
  repeated `DataFrame.loc`.
- **Slice, don't copy**: point-in-time history is an `iloc[:n]` view
  (`_SymbolData.upto`), not a growing copy.
- **Store columnar + compressed**: the bar cache is one snappy-parquet file per
  symbol+timeframe, deduped on write; never re-download covered ranges
  (`BarCache.missing_ranges`).
- **`frozen=True, slots=True`** on hot value objects (no per-instance `__dict__`).
- **Vectorise** with pandas/numpy over Python loops on the bar dimension.

## Testing rules

- **One test module per source module**; test pure functions directly.
- **No network, no real clock**: providers use `httpx.MockTransport`; the DB
  uses `sqlite:///:memory:`; randomness uses `np.random.default_rng(seed)`.
- **Prove the invariant, not just the happy path**: the backtester ships
  *no-look-ahead* causality proofs (truncating future bars must not change past
  results); SQL analytics are tested for parity against the Python analytics.
- **Migrations**: after any model change, upgrade head on a temp SQLite, run
  `alembic check` (expect "No new upgrade operations detected"), and verify a
  downgrade/upgrade round-trip. Prefer `make migration` (autogenerate) then
  renumber to `NNNN_name.py`; use `batch_alter_table` (SQLite-safe).
- **Idempotent persistence**: repositories replace per natural key
  (`run_id`/`period`) so re-runs don't duplicate. Test the re-run.
- Use `conftest.py` factories/fixtures; keep tests deterministic and fast
  (the whole suite runs in seconds).

## Adding a subsystem (the repeatable recipe)

1. `config/<x>.example.yaml` + a `<X>Config` (immutable Pydantic, validated).
2. Frozen-dataclass I/O types with `to_dict`/`to_record`.
3. Pure logic module(s) (scoring/maths), then a thin engine class.
4. `__init__.py` public exports.
5. Persistence (if any): ORM model → register in `models/__init__.py` →
   `make migration` → renumber `NNNN_*.py` → `alembic check` → repository.
6. Tests for each of the above (incl. a DB round-trip and config validation).
7. `docs/<X>.md` + a row in the README docs table + a bullet in this file.
8. Run the quality gate; commit; push to `claude/vigilant-wozniak-oueczq`.

See `/add-subsystem` and `/add-migration` skills for the exact steps.

## How to work a request (every prompt)

1. **Plan first.** For non-trivial work, write a short numbered stage map before
   editing. Reuse what exists (search first); don't re-derive established facts.
2. **Delegate independent work.** Pre-scoped sub-agents live in `.claude/agents/`:
   `engine-implementer` (opus, builds a subsystem end to end),
   `test-author` (sonnet, adds tests), `verifier` (sonnet, runs the gate +
   reviews the diff). They implement/verify only — the main session owns all
   git/commit/push. Launch independent agents in one batch so they run in
   parallel.
3. **Verify.** Run the quality gate (`/verify` or `make check`) and review the
   diff before committing.
4. **Self-critique before reporting done.** Name at least one limitation, gap or
   risk and fix it or flag it. Green checks prove it *runs*, not that it is
   *correct and complete*.

## Background-task & monitor hygiene

A machine bricked by runaway background processes is why this exists:

- **At most ONE background monitor at a time**; stop the previous before arming
  another. Don't arm a monitor for a one-time check — use a foreground command.
- **Never** use a foreground `sleep`/`until` loop to wait for an external event.
- **Leave nothing running** at the end of a turn; confirm pushes in the
  foreground.

## House style (every reply)

Be concise and lead with the result/action. Prefer tool calls over narration;
don't pre-announce ("I'll…") or over-explain; skip options you won't pursue.
Brevity is the default — expand only when the user asks for depth.

## End-of-session housekeeping

- Bump the patch `version` in `pyproject.toml` one tick per session and quote it
  in your closing report.
- Park deferred work in `docs/BACKLOG.md`.
