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

## Options recommendation — deferred follow-ups

- **Real IV / IV-rank inputs** — the options-recommendation service has no implied-vol
  data, so `iv`/`iv_rank` pass as `None` (engine defaults to vol-from-ATR and rank 0.5,
  i.e. mostly the conservative Deep ITM default). Wire an IV feed to unlock the ATM /
  spread regimes from real data.
- **Desktop Options Recommendation card** — surface `GET /options-recommendation/{symbol}`
  on the Trade Plan view (alongside the Options Eligibility card), incl. the contract,
  gates and risk disclosures. Backend + API are done; the React view is not.
- **Live-chain validation** — feed the recommended contract into the contract-level
  options-qualification gate against real quotes before display (replace the approximate
  Brenner–Subrahmanyam pricing with chain mids/greeks).

## QA findings (from docs/PRODUCTION_READINESS_TESTS.md)

- **Harden the scanner against malformed bars** (FINDING-1, medium) —
  `MomentumScanner.scan` raises `TypeError` on an un-normalized/partial frame
  instead of skipping that symbol; normalize/validate per-frame and skip bad
  ones (mirroring `pull_bars` provider-error isolation).
- **Out-of-band audit channel** (FINDING-2, low) — audit rows share the business
  transaction; write on a separate connection if a "attempted but rolled back"
  trail is needed.

## Conventions for this file

One line per item: what + where + why deferred. Keep it short; delete done items.
