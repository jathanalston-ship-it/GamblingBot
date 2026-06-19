# `mrp` Command-Line Interface

A production Typer CLI over the platform. Every command configures logging first
(rotating file + console, plain or `--json`) and resolves the database from
`DATABASE_URL` (default `sqlite:///data/momentum.db`).

```
mrp serve       launch the read-only API (uvicorn sidecar)
mrp paper-run   pull data → scan → conviction → risk → paper orders → journal
mrp scan        run the momentum scanner and print ranked candidates
mrp health      check the database connection, schema and migration state
mrp replay      print a stored session (run, trades, audit) from the ledger
```

## Logging

Configured by `momentum.core.logging.setup_logging`:

- **Console + rotating file** (`logs/mrp.log`, 10 MiB × 5 backups by default).
- **Timestamped**, ISO-8601.
- **Structured**: pass `--json` (or `MRP_LOG_JSON=1`) for one JSON object per line.
- **Crash-safe**: each record is flushed; the file rotates by size so prior
  history is never truncated.
- Env overrides: `MRP_LOG_LEVEL`, `MRP_LOG_DIR`, `MRP_LOG_JSON`.

## Commands & examples

### `mrp health`
```bash
mrp health
```
```
database: sqlite:///data/momentum.db
tables: 15 present
migration revision: 0009
status: OK
```
Exit code `0` when the connection works and all core tables exist; `1` otherwise
(e.g. before `alembic upgrade head`).

### `mrp scan`
```bash
mrp scan --symbols AAPL,MSFT,NVDA,AMZN --top 5
```
```
RANK SYMBOL      SCORE     PRICE  DIST_ATH
1    NVDA        91.40    120.50     0.000
2    AAPL        84.10    230.10     0.012
...
```

### `mrp paper-run`
Runs one full session and prints the daily report. Workflow:
**1.** pull market data → **2.** scan → **3.** conviction scores → **4.** risk
engine → **5.** paper orders → **6.** store positions → **7.** store audit events
→ **8.** session summary.
```bash
mrp paper-run --symbols AAPL,MSFT,NVDA --as-of 2026-01-05 --equity 100000
mrp paper-run --json                       # structured logs for ingestion
```
```
# Daily Report — 2026-01-05 (paper)

- **Run:** `paper-20260105`
- **Equity:** 100,000.00 → 100,000.00 (+0.00)
- **Open positions:** 1
- **Opened today:** 1 | **Closed today:** 0
...
```
Re-running the same `--as-of` is idempotent (the scheduler/journal de-duplicate).

### `mrp replay`
Reconstructs a past session from the ledger (run row + trades + audit trail).
```bash
mrp replay                        # latest run
mrp replay --run-id paper-20260105
```
```
# Replay — paper-20260105 (paper, 2026-01-05)
status=completed equity 100000.0 → 100000.0 opened=1 closed=0

## Trades: 1 open, 0 closed
- NVDA open qty=42 net=—

## Audit trail: 5 events
- 2026-01-05 16:00:00+00:00 signal_generated: momentum candidate rank 1, ...
- 2026-01-05 16:00:00+00:00 risk_adjustment: risk approve NVDA: 42->42 sh
...
```

### `mrp serve`
```bash
mrp serve --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
```
Binds loopback only (a private desktop sidecar).

## Notes

- The provider defaults to keyless **Yahoo**; `ALPACA_*` / `POLYGON_API_KEY`
  enable those providers (not yet selectable from the CLI flag — Yahoo only).
- `paper-run` / `serve` create the schema on first launch (`create_all`); for
  production use `alembic upgrade head` and verify with `mrp health`.
