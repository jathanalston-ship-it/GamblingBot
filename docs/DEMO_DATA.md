# Demo Dataset

A deterministic seed so the UI / API can be explored **without running the
scanner or pulling market data**.

## Seed it

Three ways — all call the same `momentum.demo.seed_all` (deterministic, idempotent):

```bash
alembic upgrade head        # ensure the schema exists
make seed-demo              # or: python scripts/seed_demo.py
```

- **From the desktop app:** click **"Load sample data"** in the context bar
  (`POST /actions/seed-demo`) — the fastest way to populate every screen on a
  fresh or offline install. It reloads the views when done.
- **From code:** `from momentum.demo import seed_all; seed_all(session)`. The
  seeding logic lives in the package (`src/momentum/demo.py`) so it ships in the
  desktop build; `scripts/seed_demo.py` is a thin CLI wrapper over it.

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
| Scan results | 15 ranked candidates | **Scanner**, **Candidates** |
| Conviction scores | 15 (authentic `ConvictionEngine` output) | **Conviction** |
| Opportunity tiers | 15 (Normal / Enhanced / Home Run) | Scanner / Conviction badges |
| Risk metrics | 3 windows (inception / 90d / 30d) | **Portfolio** risk card |
| Optimization results | 14 (2 studies, ranked, 1 selected each) | **Backtesting** |
| Tracked trades | 4 (3 open, 1 closed w/ realized R) + 7-day evaluation trails | **Trades** (health battery, Time Machine, journal) |
| Run + audit trail | 1 `demo` run, full event log | **Replay** (`mrp replay`) |

The 50 closed trades are the analytics dataset — they have a realistic
**positive-skew** payoff (a low win rate with a few large winners and many small,
capped losers), so the expectancy / profit-factor / largest-winner metrics render
meaningfully.

The 15 ranked scan candidates (one per universe symbol, momentum-sorted) drive the
research loop: each carries a matching **conviction score** (computed through the
real `ConvictionEngine`, not hardcoded) and an **opportunity tier**, so the
Scanner → Candidates → Conviction → Analogs path is fully populated. Selecting any
candidate also gives the Analogs view a symbol to compute against. **Every desktop
screen therefore shows realistic data straight after `make seed-demo`** — no live
scan, backtest or risk run required.

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
