# Backlog

Deferred / future work, parked here so sessions don't re-discover it. Move an
item into a subsystem doc when it becomes active.

## Trader-UI review — deferred (need market-data plumbing, not offline-testable)

These items from the daily-use UI review were intentionally deferred because they
require a live quotes/bars feed or reference data the system doesn't yet ingest;
they belong in a dedicated market-data slice with its own tests:

- **Live mark-to-market on open positions** (Paper) — current price, unrealized
  P&L, current R, distance-to-stop/target. Needs a quotes endpoint hitting the
  provider. UI has placeholder columns (% equity, per-position heat) + a caption.
- **Real OHLC price charts** with entry/exit/stop overlays (Scan inspector,
  Conviction, Replay) — needs a `/bars` endpoint serving cached OHLCV. Replay's
  excursion chart is labeled schematic in the meantime.
- **Event & liquidity columns** on candidates — earnings/ex-div flags, $ADV,
  spread, ATR — need a corporate-actions/liquidity data source.
- **Full backtest report** (equity curve, drawdown, trade list, OOS split,
  vs-benchmark) — needs per-run backtest detail persistence; Backtesting now
  renders params as labeled fields instead of raw JSON, but is still summary-only.
- **VIX / breadth** in the context bar — not in the regime feed; realized vol
  (RV) is shown as a proxy beside ADX.

## Known follow-ups

- **Stale remote branch** — `claude/admiring-feynman-n8rhuj` still exists on the
  remote; the managed git proxy returns 403 on ref deletes and the GitHub MCP
  has no delete-branch tool. Delete it from the GitHub UI. All its commits are
  contained in `claude/vigilant-wozniak-oueczq`.
- **Options pricing** — instrument-selection structures use the ATM premium
  approximation (`0.4·S·σ·√T`); swap in real option quotes at execution time.
- **Live option/IV feed** — `InstrumentContext` (IV, OI, spread, LEAPS
  availability) is supplied by the caller; wire a provider for these.
- **Plotly tearsheet** — `reporting/{plots,tearsheet,report_generator}.py`
  remain stubs; the markdown dashboard + research report cover the core today.
- **Remaining stubs** — `execution/` (`order_manager`, `live_broker`, `fills`),
  `orchestration/scheduler.py`, parts of `portfolio/` (`allocator`,
  `rebalancer`), `api/` and `cli/` are documented stubs.

## Paper-slice / orchestration follow-ups

- **Provider selection from the CLI** — `mrp` commands use keyless Yahoo; expose
  Alpaca/Polygon (with keys) behind the `--provider` flag.
- **Order/position/fill persistence** — only the journal (`trades`) and the
  `runs` registry are persisted; add an orders/positions/fills schema for a full
  execution audit trail.
- **Richer exits** — partial scale-outs and trailing stops (`ExitManager`
  currently does full-position stop/target/time exits only).
- **Live broker adapter & a real scheduler/clock loop** — the `Scheduler` is a
  serial decision point triggered by the caller, not a timed daemon.

## Trade lifecycle — deferred follow-ups

- **Link tracked trades to the journal** — a tracked trade records the
  *recommendation*; link it to the executed `trades` row (entry_signal-style FK)
  so realized outcomes can grade the reevaluation advice.
- **Options instrument at creation** — `instrument` is `"shares"`; wire the
  options-eligibility verdict into `create_from_recommendations`.
- **Desktop Trades view** — the `/trade-lifecycle` API is complete; a screen with
  health chips, action badges and per-trade strength history is UI-only work.

## Options recommendation — deferred follow-ups

- **True options-IV feed** — the IV inputs are a *realized*-vol proxy persisted on
  `scan_results` (`implied_vol`/`iv_rank`). Plug a real options-chain IV provider into the
  same two columns to replace the proxy (the engine/service/UI need no changes).
- **Live-chain validation** — feed the recommended contract into the contract-level
  options-qualification gate against real quotes before display (replace the approximate
  Brenner–Subrahmanyam pricing with chain mids/greeks).

## Desktop packaging

- **Slow shutdown can strand the single-instance lock** (startup forensics, low) —
  `will-quit` defers the quit and waits up to 5 s + 2 s for the backend tree to die;
  if a relaunch starts while the previous instance is still tearing down, the new
  launch sees the lock held and silently quits. Now *logged* (`single-instance-lock:
  another instance owns the lock`), but consider a bounded shutdown wait or a
  startup grace-retry on the lock. See `docs/STARTUP_FORENSICS.md` §3.
- **Build the backend as PyInstaller `onedir` (not `onefile`)** — onefile spawns a
  bootloader child + extracts to a temp dir on every launch (slower first paint, AV
  temp-extraction locks, and the double-process that motivated the `taskkill /T`
  tree-kill). onedir avoids the extra process and speeds startup; revisit
  `desktop/build/backend.spec` + `electron-builder.yml` extraResources.

## QA findings (from docs/PRODUCTION_READINESS_TESTS.md)

- **Out-of-band audit channel** (FINDING-2, low) — audit rows share the business
  transaction; write on a separate connection if a "attempted but rolled back"
  trail is needed.

## Conventions for this file

One line per item: what + where + why deferred. Keep it short; delete done items.
