# Demo Dataset

A deterministic seed so the UI / API can be explored **without running the
scanner or pulling market data**.

## Seed it

```bash
alembic upgrade head        # ensure the schema exists
make seed-demo              # or: python scripts/seed_demo.py
```

Seed a separate database (leaves your real one untouched):
```bash
DATABASE_URL=sqlite:///demo.db python scripts/seed_demo.py
```

Clear the demo rows again:
```bash
python scripts/seed_demo.py --reset-only
```

## What it generates

| Data | Volume | Powers (UI view) |
|---|---|---|
| Market regimes | 30 daily | Market Regime |
| Historical signals | 100 | Signals / Scanner |
| Completed trades | 50 (closed) | Trade Journal, **Analytics** |
| Portfolio snapshots | 30 daily (equity curve) | Dashboard, Portfolio |
| Run + audit trail | 1 `demo` run, full event log | **Replay** (`mrp replay`) |

The 50 closed trades are the analytics dataset — they have a realistic
**positive-skew** payoff (a low win rate with a few large winners and many small,
capped losers), so the expectancy / profit-factor / largest-winner metrics render
meaningfully.

## Properties

- **Deterministic** — fixed RNG seed, identical dataset every run.
- **Idempotent** — all rows are tagged (`run_id` / `model_version` = `demo`) and
  cleared before re-seeding, so running it repeatedly never duplicates.
- **Aligned for replay** — trades, the `demo` run and its audit events share
  `run_id == "demo"`, so `mrp replay` shows the trades and their event history
  together.

## Verify

```bash
mrp replay --run-id demo          # the seeded session: trades + audit trail
mrp health                        # connection + schema
mrp serve                         # then open the desktop app over the API
```
