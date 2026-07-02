# Paper Trading Vertical Slice

The smallest end-to-end path from a scan to a recorded trade:

```
Scanner → Conviction → Risk sizing → Paper order → Position tracking → Journal entry
```

Every stage reuses an already-implemented engine; this slice adds the execution
primitives, the in-memory portfolio, the trade journal and the orchestrator that
wires them together. It is deterministic (no clock, no randomness, no network)
and re-runnable.

## Modules

### Execution (`src/momentum/execution/`)

- **`order.py`** — `Order` is the routable unit with a guarded lifecycle
  (`NEW → SUBMITTED → PARTIALLY_FILLED → FILLED | CANCELLED | REJECTED`); illegal
  transitions raise `InvalidOrderStateError`. `Fill` is one immutable execution
  (price, shares, fees, timestamp) exposing `notional`, `signed_shares` and
  `cash_flow`.
- **`broker.py`** — the `Broker` protocol (`submit` / `cancel` / `name`) and the
  immutable `OrderRequest`. The request carries a `reference_price` (the
  decision-time price) and a `client_order_id` idempotency key.
- **`paper_broker.py`** — `PaperBroker` fills synchronously and deterministically:
  market orders at the reference adjusted by the shared `slippage` model, limit
  orders only when marketable (at the limit), stop orders rejected. Commission
  comes from the shared `commission` model, so paper costs match the backtester.
- **`execution_config.py`** — immutable `ExecutionConfig` (slippage bps,
  commission per share + minimum) with `from_yaml` / `config_hash`; see
  `config/execution.example.yaml`.

### Portfolio (`src/momentum/portfolio/`)

- **`position.py`** — `Position` accumulates fills into a VWAP entry, tracks
  realised/unrealised P&L, the protective stop and the live R-multiple, and
  bridges to the risk engine via `to_open_position()`.
- **`portfolio.py`** — `Portfolio` is the authoritative cash + open/closed
  ledger. `on_fill` moves cash and routes the fill; `mark_to_market` revalues;
  `to_account_state()` hands the live book to the risk gateway so sizing always
  sees real heat and exposure.
- **`journal.py`** — `TradeJournal` persists each trade's entry (`open_trade`)
  and exit (`close_trade`) to the `trades` table. Entry is idempotent per
  `(run_id, symbol)`; close computes gross/net P&L, R-multiple, return and
  holding days. All SQL stays in `TradeRepository`.

### Orchestration (`src/momentum/orchestration/`)

- **`pipeline.py`** — `DailyPaperPipeline.run(scan, run_id, regime)` processes
  each ranked candidate: score conviction → gate on a minimum band → derive a
  per-trade **risk budget** from the conviction band → size/stop/vet through the
  risk gateway → route an approved order to the paper broker → apply the fill to
  the portfolio (and set its stop) → journal the open trade. Symbols already held
  are skipped, so a re-run with the same `run_id` is idempotent. Each candidate
  yields an explainable `TradeDecision`; the run returns a `PipelineReport`.

## Flow

1. **Scanner** produces a `ScanResult`; `pipeline.run` iterates its `candidates`.
2. **Conviction** — `ConvictionEngine.score` turns the candidate's features
   (momentum, relative volume, distance-to-ATH, sector RS) plus the market regime
   into a 0–100 score and band; below `min_conviction_band` the candidate is
   rejected.
3. **Risk sizing** — the conviction band sets a per-trade risk budget
   (`DynamicRiskBudgetEngine`), which drives `RiskManager.evaluate` to size, stop
   and vet the trade against portfolio heat / exposure / drawdown limits.
4. **Paper order** — an approved assessment becomes an `OrderRequest` filled by
   `PaperBroker`.
5. **Position tracking** — the fill updates the `Portfolio`; the initial stop is
   recorded on the `Position`.
6. **Journal entry** — `TradeJournal.open_trade` writes the open `trades` row.

## Since the original slice

Later sessions filled the original gaps:

- **Order/fill persistence** — every routed order (entry and exit) is snapshotted
  to the `orders` table and its executions to `fills` (migration `0026`),
  idempotent per client order id (`OrderRepository.persist` upserts the order and
  replaces its fills). Read via `GET /orders`.
- **Exits** — the orchestration engine runs a full exit pass (stop / trailing
  stop / target / partial scale-out / time-stop); see `docs/ORCHESTRATION.md`.
- **Partial-exit accounting** — `TradeJournal.scale_out` reduces the open row's
  quantity and banks the partial P&L (`scaled_out_quantity`/`scaled_out_pnl`);
  `close_trade` folds it into the final gross/net/R, and recovery reproduces the
  cash. `TradeJournal.update_stop` persists trailing-stop moves
  (`trades.current_stop`).
- **Scheduler/recovery and the append-only audit log** — see
  `docs/ORCHESTRATION.md` and `docs/AUDIT_LOGGING.md`.

## Limitations (deliberately out of this slice)

- **No live broker adapter** — paper-only by design; the `Broker` protocol +
  persisted orders/fills are the seam a live adapter plugs into. See
  `docs/BACKLOG.md`.
