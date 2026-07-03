# Brokerage Simulation

Momentum Lab no longer thinks in terms of "paper trades" — it owns a complete
brokerage simulation. The decision engine talks to a **Brokerage interface**;
the first implementation is the **PaperBrokerage** venue. A future live
adapter implements the same interface and requires zero changes upstream.

```
Decision Engine
      ↓
Brokerage (protocol)          src/momentum/brokerage/interface.py
      ↓
PaperBrokerage (venue)        src/momentum/brokerage/paper.py
  ├── OMS                     oms.py        (order lifecycle state machine)
  ├── ExecutionSimulator      execution_sim.py (spread/slippage/liquidity)
  ├── Account math            accounts.py   (settlement, BP, drawdown, sharpe)
  └── broker_* tables         persistence/models/broker.py (migration 0027)
```

## The interface (`Brokerage` protocol)

Trading: `place_order`, `cancel_order`, `modify_order`, `close_position`.
Reads: `get_account`, `get_portfolio`, `get_buying_power`, `get_positions`,
`get_orders`, `get_fills`, `get_history`. **No UI shortcuts** — every mutation
and every read flows through this surface (HTTP: `/brokerage/*`).

## Accounts (Prompt 2)

Every account tracks cash, **settled vs unsettled** cash (T+n business-day
settlement on sale proceeds — only settled cash counts toward buying power),
equity, portfolio value, buying power (settled × margin multiplier), used
buying power (open cost basis), available margin, open risk (distance-to-stop
exposure), daily P&L (vs the day-roll baseline), total P&L, max drawdown,
trade count, win rate, Sharpe and expectancy (R). The **account history is
immutable**: every material change (open, fill, mark, settle, day-roll)
appends a `broker_account_history` row and the repository's `delete` raises.

## Order management (Prompt 3)

Order types: **Market, Limit, Stop, Stop-Limit, Trailing-Stop** (percent or
dollar trail; the trigger only ever ratchets tighter), **Bracket** (entry +
take-profit + stop-loss children that activate when the entry fills) and
**OCO** (one fill cancels the siblings). Partial fills, cancels, rejects and
day-order expiry are all first-class.

Lifecycle: `SUBMITTED → ACCEPTED → WORKING → (PARTIALLY_FILLED) →
FILLED | CANCELLED | REJECTED | EXPIRED`. Illegal transitions raise; **every
transition is persisted append-only** to `broker_order_events` (the
repository refuses deletes) — history is never overwritten.

Validation at placement: buying-power check on entries (estimated from the
limit/stop reference, re-checked against the real quote at execution), no
selling more than is held (no naked shorts), open-order cap.

## Execution simulation (Prompt 6)

Market orders execute using the current **bid/ask** — a buy pays the ask, a
sell hits the bid, **never the midpoint** — plus participation-driven
slippage that grows with the order's share of the bar's volume, widens for
illiquid names, at the open/close (first/last 30 minutes) and for option
instruments, and **partial-fills** when the order exceeds the per-tick
participation cap. When only bar data exists the two-sided quote is
*estimated* (base spread widened by realized range and illiquidity) and the
fill reason says so. Realism levels: `basic` (frictionless), `realistic`
(modeled), `pessimistic` (doubled frictions). Every knob lives in
`config/brokerage.example.yaml`.

## Market data

The venue advances on `process_tick(quotes)`: resting orders expire, ratchet,
trigger and fill; open positions mark to market (MFE/MAE high-water marks).
`POST /brokerage/tick` builds quotes from the freshest cached bars (live
fallback) for every symbol with an open order or position;
`api/brokerage_service.tick` also accepts intraday last prices to override
the bar close.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/brokerage/orders` | place (idempotent per `client_order_id`) |
| DELETE | `/brokerage/orders/{id}` | cancel (cascades to bracket children) |
| PATCH | `/brokerage/orders/{id}` | modify qty / limit / stop / trail |
| POST | `/brokerage/positions/{sym}/close` | flatten or reduce |
| POST | `/brokerage/tick` | advance the venue from fresh bars |
| GET | `/brokerage/account · portfolio · buying-power · positions · orders[/{id}] · fills · history` | full read surface |

## Tests

`tests/unit/brokerage/`: the OMS state machine (legal/illegal transitions,
trailing ratchet, trigger semantics), the execution simulator (ask-not-mid,
partials, realism ordering, time-of-day), account math (settlement over
weekends, drawdown, Sharpe, metrics) and the venue end-to-end (bracket → OCO,
trailing exit, day expiry, settlement reducing buying power, append-only
history, idempotent placement). Route tests cover the HTTP surface. The venue
clock is injectable — no real clock in tests.
