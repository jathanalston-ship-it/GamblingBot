# Watchlist Performance Tracking

Does the platform's advice actually work? Every generated watchlist entry is stored
with its point-in-time prediction and then **tracked forward against real bars** —
1-day / 1-week / 1-month returns plus the maximum favorable / adverse excursion —
and scored into per-horizon **scorecards** and **prediction-quality** rankings so
the **Daily / Weekly / Monthly** watchlists can be compared and the system can learn
whether its recommendations are useful.

## What is stored

The prediction already lives on `watchlist_entries` (migration `0010`): **date**,
**ticker**, **conviction**, **rank**, **expected move**, **expected horizon**, plus
the mini trade-plan fields (expected risk %, reward:risk, risk rating). Tracking adds
one row per entry on `watchlist_performance` (migration `0014`), idempotent per
`(run_id, as_of, horizon, symbol)`:

| Field | Meaning |
|---|---|
| `reference_price` | close on the generation date (the baseline) |
| `ret_1d` / `ret_1w` / `ret_1m` | forward returns at 1 / 5 / 21 trading days |
| `mfe` / `mae` | max favorable / adverse excursion over the 1-month window |
| `bars_tracked`, `complete` | forward bars observed; whether the 1-month window elapsed |
| `last_price`, `last_tracked_date` | most recent observation |

The prediction (conviction, rank, expected move, horizon) is denormalized onto the
row so every scorecard is a single-table read.

## What is measured

**Scorecard** (per horizon): average 1d/1w/1m return, **hit rate** (ret_1m > 0),
average MFE/MAE, **E-ratio** (avg MFE / |avg MAE|), expected-move capture, and the
**top-5 rank edge** (avg return of the top picks minus the rest).

**Prediction quality** (per horizon): the **information coefficient** of conviction
vs realised return (`ic_conviction`) and of rank vs realised return (`rank_ic`), the
hit rate, a conviction **calibration** table (avg conviction vs avg return per
bucket) with a monotonicity flag, and a blended 0-100 **quality score** (50 ≈ no
skill). Horizons are ranked best-first and the `best_horizon` is surfaced.

These are long-biased momentum picks, so a positive return is "good".

## How tracking runs

Tracking is pure given bars, so it is offline-testable. The operator-console action
pulls bars for every watchlisted symbol over a trailing window ending today — which
contains the forward bars for *prior* generations — and upserts the results
(idempotent; a still-maturing generation is refined as more bars arrive):

```
POST /actions/track-watchlist-performance      # background job; pulls bars + tracks
GET  /watchlist-performance                     # scorecards + quality (the comparison)
GET  /watchlist-performance/entries[?horizon=]  # tracked entries
```

## Implementation

- **Config** — `WatchlistPerformanceConfig` (windows, buckets, min sample);
  `config/watchlist_performance.example.yaml`.
- **Types** — frozen dataclasses (`EntryPrediction`, `PerformanceRecord`,
  `HorizonScorecard`, `PredictionQuality`, `CalibrationBucket`,
  `WatchlistPerformanceReport`) with `to_dict` / `to_record`.
- **Tracking** — `watchlist_performance/tracking.py`, pure forward-return + MFE/MAE
  computation (`compute_forward`) plus a bars adapter (`track_entry`).
- **Scoring** — `watchlist_performance/scoring.py`, pure scorecards + IC/calibration
  + the blended quality score and report builder.
- **Persistence** — `WatchlistPerformance` model + migration `0014` +
  `WatchlistPerformanceRepository.upsert_many` (idempotent per generation).
- **Service** — `api/watchlist_performance_service.py` (track with injected bars;
  read the report + entries).
- **Action / CLI** — `actions.track_watchlist_performance` pulls bars via the
  configured provider; `POST /actions/track-watchlist-performance`.
- **Desktop** — a **WL Performance** view: the Daily/Weekly/Monthly scorecard
  comparison, the prediction-quality ranking, the conviction calibration of the best
  horizon, and a **Track performance** button. Demo data seeds it.

## Notes & limitations

- The default tracking is **long-only** (watchlists are bullish); shorts are out of
  scope.
- A generation's 1-month metrics are only **final once `complete`** — earlier reads
  show partial windows (fewer `bars_tracked`, possibly `ret_1m = null`).
- IC/quality need a reasonable sample (`min_sample`) before `best_horizon` is set.
