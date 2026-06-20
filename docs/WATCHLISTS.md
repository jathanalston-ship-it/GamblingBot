# Multi-Horizon Watchlists

Actionable, ranked watchlists for three horizons — **Today**, **This Week**,
**This Month** — each surfacing the names with the highest conviction *for that
timeframe*, with the trade context a trader needs to act.

## Each entry

| Column | Source |
|---|---|
| Ticker | conviction / scan |
| Conviction | horizon-specific score (0-100) |
| Rank | position within the horizon list |
| Sector | scan |
| Risk Rating | Low / Medium / High from expected risk |
| Expected Horizon | trading days (1 / 5 / 21) |
| Expected Move % | `ATR/price × move_sigma × √days` |
| Expected Risk % | `ATR/price × stop_atr_mult` (planned stop) |
| Expected Reward/Risk | `expected_move ÷ expected_risk` |

## Methodology

Each horizon **re-weights the same normalized conviction factors** to emphasise
the signals that matter on that timeframe, then ranks the universe by the
resulting horizon conviction and keeps the top *N* (`size`):

- **Daily** (short term) — relative volume, momentum, regime (fast flow).
- **Weekly** (medium term) — momentum + trend + sector + regime (balanced).
- **Monthly** (long duration) — trend quality, historical analogs, sector
  leadership, ATH proximity (durability).

So the same universe produces three *different* rankings. Expected move/risk are
ATR-derived and scale with the horizon (`√days`), so reward:risk rises with
duration against a fixed ATR stop. Weights, sizes, horizon lengths and risk-rating
thresholds are all tunables in `config/watchlist.example.yaml`.

## Components

- **Config** — `WatchlistConfig` / `HorizonProfile` (immutable Pydantic, validated;
  `config/watchlist.example.yaml`).
- **Engine** — `momentum/watchlist/engine.py`, a pure
  `(candidates, config) -> {horizon: [entries]}` function.
- **Persistence** — `watchlist_entries` table (migration `0010`), one row per
  ranked name per horizon per generation. Every generation is kept, so watchlists
  can be compared over time. `WatchlistRepository.replace_for` makes re-generating
  a date idempotent.
- **Service** — `api/watchlist_service.py` joins the latest conviction scores with
  their scan context (sector, price, ATR), runs the engine, persists, and serves
  reads + comparisons.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/watchlists` | Full Today/Week/Month set for a date (latest if unset). |
| `GET` | `/watchlists/{horizon}` | One horizon's ranked list. |
| `GET` | `/watchlists/dates` | Distinct generation dates (history). |
| `GET` | `/watchlists/compare?horizon=&base=&against=` | Diff two generations: entered / dropped / rank moves. |
| `POST` | `/actions/generate-watchlists` | Generate + persist from current conviction (operator-console job). |

## Desktop

The **Watchlists** view (left rail) has three horizon tabs, a table with every
column above, a **date selector** (history), a **Generate** button, and a
**Compare** mode that diffs two generations (entered / dropped / held with rank +
conviction deltas). The demo seeder (`Load sample data`) generates two dated
watchlists so the screen and comparison work out of the box.
