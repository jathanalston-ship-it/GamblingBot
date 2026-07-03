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

## Live-integration architecture (adapter / capabilities / router / sync)

The decision engine never knows whether it is trading paper, simulation or
live — it emits an `OrderTicket` and everything else is routing:

- **`BrokerAdapter`** (`adapter.py`) — a `Brokerage` implementation paired
  with its declared `BrokerCapabilities`; the ONLY place venue-specific
  knowledge may live. `PaperBrokerAdapter` wraps the internal venue by pure
  delegation; a live adapter (IBKR, Alpaca live, …) implements the same
  pair and **requires zero changes** to the scanner, trade manager, risk
  manager or portfolio manager — enforced by
  `test_decision_engines_never_import_a_concrete_broker` (source-level
  check that those packages never name a concrete venue).
- **`BrokerCapabilities`** (`capabilities.py`) — immutable declaration of
  order types, time-in-forces, instruments, brackets/OCO/short/fractional
  support and per-order limits, with `rejection_reason(ticket)`.
- **`OrderRouter`** (`router.py`) — the single door every instruction walks
  through: pick the configured adapter (multi-broker registry, named or
  default), refuse capability-unsupported tickets with a named reason
  **before the venue sees them**, delegate, and record every decision in a
  bounded routing log. Wired behind `/brokerage/orders` (place / cancel /
  modify / close) via `brokerage_service.build_router` — swapping venues is
  configuration, not code.
- **`ExecutionReport`** (`reports.py`) — the normalized answer
  (action/broker/mode/accepted/reason/order/ts) whatever the venue.
- **`PositionSync` / `AccountSync`** (`sync.py`) — read-only fetch +
  normalize of venue positions/account into plain snapshots: the raw
  material broker reconciliation compares against the local database.

HTTP: `GET /brokerage/capabilities` (every registered broker + the routing
default), `GET /brokerage/routing-log` (recent accepted/refused decisions).
Tests: `tests/unit/brokerage/test_router.py`.

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

## Position engine (Prompt 4)

Every position row tracks average cost, realized + unrealized P&L, today's
gain (vs the day-roll baseline price), maximum favorable / adverse excursion
(marked on every tick), the open R multiple (vs the initial stop distance),
time in trade and the stop. Option structures ride the same abstraction via
``instrument`` + ``multiplier`` (a contract is 100 units); future instruments
add an ``InstrumentType`` and a multiplier, nothing else. Health, thesis and
exit recommendation come from the trade-lifecycle engine, joined by symbol in
the portfolio-manager service.

## Portfolio Manager (Prompt 5)

`brokerage/portfolio_manager.py` (pure) reads the whole book at once:
portfolio exposure, cash allocation, maximum sector concentration, maximum
single-position exposure, average pairwise correlation (from recent daily
returns), value-weighted portfolio beta (vs SPY), open risk, expected
downside (stops where defined; a 10% assumption where not) and capital
efficiency (deployed $ per $ of defined risk). It then emits **justified
suggestions** — Increase / Reduce / Close / Add / Diversify — each quoting
the measurement that triggered it (never a black box).
`GET /brokerage/portfolio-analysis`; inputs assembled by
`api/portfolio_manager_service.py` (positions + tracked-trade health/sector +
bar-cache returns + latest regime).

## Desktop

The **Brokerage** view (nav: Today → Brokerage) is the full venue UI:
account strip (equity, settled/unsettled cash, buying power, daily/total
P&L, drawdown, win rate / expectancy / sharpe), a place-order form (market /
limit / stop / stop-limit / trailing-stop + bracket TP/SL), the positions
table (value, unrealized, today, R, stop, close button), the order blotter
(status chips, fills, cancel, and the **full persisted lifecycle** expandable
per order) and the Portfolio Manager panel (measurements + suggestions).
"Process market tick" advances the venue from the freshest cached bars.

## Automatic management on every scan (Prompt 7)

`run_scan` advances the venue right after the tracked-trade reevaluation
step: `brokerage_service.tick` builds quotes for every symbol with an open
order or position (freshest cached bars, overridden by the scan's intraday
prices) and lets resting orders — brackets, stops, trailing stops — expire,
trigger and fill. The scan summary reports `brokerage_orders_filled` /
`brokerage_orders_expired`. Everything the venue does is journaled
append-only; `GET /brokerage/timeline` merges account events, order
transitions and fills into one chronological story, and historical decisions
are never modified (the events tables refuse deletes).

## Portfolio Replay (Prompt 8)

`GET /brokerage/replay/timestamps` lists every replayable instant (each
account-history row, downsampled ≤ 1000); `GET /brokerage/replay/state?ts=…`
reconstructs the venue at that instant **from the immutable trail**: the
newest account snapshot at-or-before `ts`, each order's status *at that
moment* (its event trail replayed up to `ts`), and the positions **as they
were then** — quantities, running weighted-average cost and realized P&L
rebuilt from the fill trail (never the mutable current position rows, so a
position later reduced or closed replays at its earlier size), priced at
the last execution at-or-before `ts` (stated in the payload). Nothing is recomputed, so the replay can never disagree
with what happened. The Brokerage view's **Portfolio Replay** card drives it:
play / pause / step / jump via a slider over the timeline
(`api/brokerage_replay_service.py`; `tests/unit/brokerage/test_replay.py`
proves flat-before-entry, working-children-mid-session, OCO-cancel-at-end
and read-only replay).

## Performance attribution (Prompt 9)

`analytics/dollar_attribution.py` (pure) attributes **every closed dollar**
with no black boxes:

- **Per-trade identity** — `net = opportunity − give_back − fees`, always
  summing back to the net: *opportunity* is the move the scanner actually
  found (MFE × initial risk), *give_back* is what trade management left on
  the table. A negative opportunity was bad selection; a big give-back on a
  big opportunity was bad management. Trades without MFE are counted
  honestly as "opportunity unknown", never invented.
- **Driver tables** — net dollars grouped by market regime, sector, entry
  reason (scanner quality), exit reason (stop management), holding-period
  bucket (timing) and instrument (options selection); each row shows n,
  dollars and share of total.
- **Sizing effect** — actual dollars vs the counterfactual where every trade
  risked the account average (`r × avg_risk`): the difference is exactly
  what position sizing added or cost.

`GET /attribution` (`api/attribution_service.py` reads the closed-trade
ledger; MFE is stored in R, so opportunity $ = mfe × initial_risk); the
Analytics view's **Dollar Attribution** card renders the identity totals and
every driver table. Tests: `tests/unit/analytics/test_dollar_attribution.py`
(identity sums exactly, honest unknowns, driver grouping/shares, the sizing
counterfactual, empty input).

## Investment Committee

Every automated trade action passes through a committee review
(`src/momentum/committee/`, pure engine + `committee_meetings` table,
migration `0028`, append-only — minutes are never edited or deleted).

Seven members each cast **BUY / HOLD / REDUCE / EXIT** with a confidence and
a measurable justification (a member with no data votes HOLD at confidence 0
— an explicit abstention, never silence): **Scanner** (momentum score),
**Conviction Engine** (score + band), **Trade Manager** (latest thesis
health + advice), **Risk Manager** (portfolio-heat headroom), **Portfolio
Manager** (book-level suggestion), **Market Regime Engine** (bull/bear
context) and **Options Engine** (leverage eligibility). The final decision
is the confidence-weighted stance, and its record explains **agreement**
(who backs it and why), **disagreement** (each dissenter named with their
evidence — a neutral HOLD is not dissent), **confidence** and the deciding
**evidence** in a plain-language narrative.

All seven members receive real inputs: the Portfolio Manager reads the
merged book (open journal trades + open venue positions) through the pure
whole-book analysis and votes on this symbol's suggestion (falling back to
book-wide warnings like sector crowding); the Options Engine votes from the
options-eligibility recommendation when the setup has one. Members without
data still abstain explicitly.

Wiring: `take_trade` convenes an *entry* meeting (persisted even when the
trade proceeds; a decisive committee **EXIT blocks the entry** and the
refusal quotes the dissent); every scan reevaluation with a non-Hold
recommendation convenes a *manage* meeting; `POST /committee/convene/{sym}`
holds an on-demand review. Reads: `GET /committee/meetings[?symbol=]`,
`GET /committee/meetings/{uid}`. The Trade Plan view's **Investment
Committee** card shows the latest meeting (vote chips + justifications +
narrative) with a Convene button. Tests: `tests/unit/committee/`
(seven-member invariants, bull/broken/dissent scenarios, evidence payloads,
persisted-and-immutable minutes, routes).
