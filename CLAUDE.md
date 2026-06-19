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
  portfolio-heat ceiling (reusing `risk.heat`). Feeds the risk gateway's sizing.
  See `docs/RISK_BUDGET.md`.

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
