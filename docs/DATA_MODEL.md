# Data Model — Persistence & Audit Schema

SQLite (WAL mode) via SQLAlchemy 2.0 for research; the repository pattern keeps the schema swappable to Postgres for production. Every model lives in `src/momentum/persistence/models/`.

> **Status:** Schema specification only — no ORM code implemented yet.

The schema is designed around one requirement: **full auditability and reproducibility.** Raw inputs, every decision, and every outcome are all persisted and linked back to the `run` that produced them.

---

## 1. Entity-relationship diagram

```mermaid
erDiagram
    INSTRUMENTS   ||--o{ DAILY_BARS         : "has"
    INSTRUMENTS   ||--o{ CORPORATE_ACTIONS  : "has"
    INSTRUMENTS   ||--o{ SIGNALS            : "generates"
    INSTRUMENTS   ||--o{ POSITIONS          : "held as"
    INSTRUMENTS   ||--o{ TRADES             : "traded as"

    RUNS          ||--o{ UNIVERSE_SNAPSHOTS : "produces"
    RUNS          ||--o{ SIGNALS            : "produces"
    RUNS          ||--o{ RISK_ASSESSMENTS   : "produces"
    RUNS          ||--o{ ORDERS             : "produces"
    RUNS          ||--o{ TRADES             : "produces"
    RUNS          ||--o{ EQUITY_CURVE       : "produces"
    RUNS          ||--o{ RISK_EVENTS        : "produces"

    SIGNALS           ||--|| RISK_ASSESSMENTS : "evaluated by"
    RISK_ASSESSMENTS  ||--o| ORDERS           : "approves"
    ORDERS            ||--o{ FILLS            : "filled by"
    POSITIONS         ||--o| TRADES           : "closes into"

    INSTRUMENTS {
        int    id PK
        string symbol
        string name
        string sector
        string industry
        date   listed_on
        date   delisted_on
    }
    DAILY_BARS {
        int    id PK
        int    instrument_id FK
        date   session_date
        float  open_raw
        float  high_raw
        float  low_raw
        float  close_raw
        float  close_adj
        bigint volume
        string source
    }
    CORPORATE_ACTIONS {
        int    id PK
        int    instrument_id FK
        date   ex_date
        string action_type
        float  ratio_or_amount
    }
    UNIVERSE_SNAPSHOTS {
        int    id PK
        int    run_id FK
        date   as_of
        int    instrument_id FK
        bool   eligible
        json   screen_values
    }
    SIGNALS {
        int    id PK
        int    run_id FK
        int    instrument_id FK
        datetime ts
        string signal_type
        string direction
        json   features
    }
    RISK_ASSESSMENTS {
        int    id PK
        int    run_id FK
        int    signal_id FK
        string verdict
        int    requested_qty
        int    approved_qty
        float  entry_ref
        float  initial_stop
        float  stop_distance
        float  risk_dollars
        float  vol_estimate
        float  heat_before
        float  heat_after
        string binding_constraint
        json   reasons
    }
    ORDERS {
        int    id PK
        int    run_id FK
        int    risk_assessment_id FK
        int    instrument_id FK
        string side
        string order_type
        int    qty
        float  limit_price
        string status
        string idempotency_key
        datetime created_at
    }
    FILLS {
        int    id PK
        int    order_id FK
        int    qty
        float  price
        float  commission
        float  slippage
        datetime filled_at
    }
    POSITIONS {
        int    id PK
        int    run_id FK
        int    instrument_id FK
        int    qty
        float  avg_price
        float  current_stop
        float  unrealized_pnl
        string status
        datetime opened_at
        datetime closed_at
    }
    TRADES {
        int    id PK
        int    run_id FK
        int    instrument_id FK
        datetime entry_ts
        datetime exit_ts
        float  entry_price
        float  exit_price
        int    qty
        float  initial_risk
        float  r_multiple
        float  pnl
        float  fees
        float  mae
        float  mfe
        string exit_reason
    }
    EQUITY_CURVE {
        int    id PK
        int    run_id FK
        date   session_date
        float  equity
        float  cash
        float  gross_exposure
        float  net_exposure
        float  portfolio_heat
        float  drawdown
    }
    RISK_EVENTS {
        int    id PK
        int    run_id FK
        datetime ts
        string event_type
        string detail
    }
    RUNS {
        int    id PK
        string mode
        string config_hash
        string git_commit
        int    rng_seed
        json   params
        datetime started_at
        datetime finished_at
        string status
    }
```

---

## 2. Table responsibilities

### Reference / input data
| Table | Role |
|---|---|
| **instruments** | Security master: symbol, name, sector/industry, listing & delisting dates (delisting dates are what make backtests survivorship-bias-free). |
| **daily_bars** | OHLCV per `(instrument, session_date)`. Stores **both** raw and adjusted closes so adjustments are transparent and reproducible. `source` records provenance. |
| **corporate_actions** | Splits/dividends used to derive `close_adj`. Keeping them means adjustments can be recomputed and audited. |

### Decision trail (the audit core)
| Table | Role |
|---|---|
| **universe_snapshots** | Point-in-time record of which names were eligible and the exact screen values — *"what could we have traded that day?"* |
| **signals** | Every signal with the full `features` vector that produced it — *"what did the strategy see?"* |
| **risk_assessments** | One row per proposed trade: verdict, sizing math, the binding constraint, and reasons — *"why this size / why rejected?"* The spine of risk auditability. |
| **risk_events** | Limit breaches, circuit-breaker trips, drawdown-throttle changes — *"when did protection engage?"* |

### Execution & outcome
| Table | Role |
|---|---|
| **orders** | Submitted orders with `idempotency_key` (prevents duplicate sends) and lifecycle `status`. Linked to the `risk_assessment` that authorized them — no order without an approval. |
| **fills** | Executions per order, including modeled `slippage` and `commission`, so realized vs intended price is always inspectable. |
| **positions** | Open/closed position snapshots with live `current_stop` and P&L. |
| **trades** | Closed round-trips with `r_multiple`, `pnl`, `fees`, `mae`/`mfe` and `exit_reason` — the atomic unit for all of `analytics/`. |
| **equity_curve** | Daily account snapshot: equity, cash, exposure, **portfolio_heat**, drawdown — drives performance + the drawdown throttle. |

### Reproducibility
| Table | Role |
|---|---|
| **runs** | The registry every other row points to. Captures `mode`, `config_hash`, `git_commit`, `rng_seed` and `params`. Given a `run_id`, a result is regenerable bit-for-bit, and any two runs are directly comparable. |

---

## 3. Auditability guarantees

1. **No order without a recorded approval.** `orders.risk_assessment_id` is mandatory; the risk verdict that authorized any trade is always retrievable.
2. **Full lineage.** `signal → risk_assessment → order → fill → position → trade`, all tagged with `run_id`. Any trade can be traced back to the exact features and risk math behind it.
3. **Append-only audit log.** `persistence/audit.py` writes an immutable event stream in parallel to the relational tables; rows are never updated in place for decision records.
4. **Reproducible inputs.** Raw bars + corporate actions are stored, so the adjusted series a decision used can always be rebuilt.
5. **Reproducible runs.** `config_hash` + `git_commit` + `rng_seed` pin code, parameters and randomness.

---

## 4. Indexing & integrity notes (for implementation)

- Unique constraint on `daily_bars(instrument_id, session_date)`; index on `session_date` for range scans.
- Unique constraint on `orders(idempotency_key)`.
- Index foreign keys used by analytics: `trades(run_id)`, `equity_curve(run_id, session_date)`, `risk_assessments(run_id, signal_id)`.
- `runs.config_hash` indexed for fast experiment comparison.
- SQLite pragmas: `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL` for research throughput.
