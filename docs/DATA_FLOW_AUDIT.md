# Data Flow Audit — where every screen's data actually comes from

A complete, code-verified trace of the read path behind each desktop screen:
the endpoint, the service, the repository, the tables, and **the origin of the
data** — so we can answer definitively *"is this live Yahoo data, cached data,
config, the database, or the demo seeder?"* and *"can stale/demo data shadow
live data?"*

## TL;DR — the root cause of "still showing demo/frozen data"

1. **No screen pulls live market data on read.** Every screen listed below is a
   pure **database read**. Live Yahoo bars are pulled in exactly **one** place:
   the `POST /actions/scan` action (`actions.run_scan` → `pull_bars` →
   `provider.get_bars`). Refresh-data and paper-session also pull bars; no `GET`
   does. So "prices look frozen" is expected until a **scan is run** — the screens
   render whatever is in the DB.

2. **Demo and live rows live in the same tables.** The demo seeder
   (`src/momentum/demo.py`, every row tagged `run_id="demo"`) and a live scan
   (`run_id="scan-YYYYMMDD"`) both write `scan_results`, `conviction_scores`,
   `market_regimes`, `watchlist_entries`, `portfolio_snapshots`, `risk_metrics`,
   `trades`, `signals`, `opportunity_classifications`, `optimization_results`,
   `runs`, `audit_log`.

3. **Most read queries do NOT exclude demo.** The read services
   (`services.list_scans/list_conviction/list_snapshots/list_risk_metrics/
   latest_regime/list_trades`) filter `run_id` **only if one is supplied**, then
   `ORDER BY as_of DESC`. With no `run_id` selected they return **newest row by
   date regardless of source** — so a demo row dated later than your last live
   scan **shadows** it. Only `watchlist_service._load_candidates` actively prefers
   live over demo (the fix from the live-pipeline work); the per-symbol screens do
   not.

This is why the symptoms appear: same symbols repeat (demo's fixed 15-symbol
set), conviction/scan look disconnected (read straight from the table, not
re-derived live), and prices look frozen (no read pulls Yahoo). The remedy is a
**Production Data Mode** that purges/ignores demo rows (next task).

## Sources of truth (the master table)

| Source | What it is | Where | Written by | Read by (screens) |
|---|---|---|---|---|
| **Yahoo (live)** | Live OHLCV bars | `data/providers/yfinance.py` via `orchestration.session.pull_bars` | `POST /actions/{scan,refresh-data,paper-session,track-watchlist-performance}` only | **None directly** — only the scan/paper *actions*, never a screen read |
| **Cached data** | Parquet bar cache | `data/cache.py` (`BarCache`, `MRP_BAR_CACHE`) | `refresh_data` action | Backtest/scan *inputs* if used; **no screen reads it directly** |
| **Config files** | Universe + tunables | `config/*.example.yaml` via `core/config_paths.load_config` | shipped / user override | Universe selection, scanner/conviction/regime config (inputs to the scan action) |
| **Demo Seeder** | Deterministic sample rows, **all `run_id="demo"`** | `src/momentum/demo.py` (`seed_all`) | `POST /actions/seed-demo`, Reset+Demo | **Every** DB-backed screen (shares tables with live) |
| **Database Persistence** | Rows written by live activity | the `runs`-tagged tables | live scan (`scan-YYYYMMDD`), paper/orchestration sessions, watchlist generation | **Every** screen below |

## Per-screen trace

Legend — **Live?** = does the screen's *read* path request live market data.
**Shadow?** = can stale/demo data be shown in place of live data.

| Screen | Endpoint(s) | Service | Repository / query | Tables read | Origin | Live? | Shadow? |
|---|---|---|---|---|---|---|---|
| **Command Center** | `GET /command-center` | `command_center.command_center()` (aggregates) | `watchlist_service`, `services.latest_regime/list_conviction/performance_summary`, `lifecycle_service` | `conviction_scores`, `scan_results`, `market_regimes`, `watchlist_entries`, `portfolio_snapshots`, `trades`, `setup_lifecycles` | Demo **or** DB persistence | No | **Yes** — `latest_regime`/`list_conviction` pick newest-by-date with no demo exclusion; watchlist section prefers live |
| **Scan** | `GET /universe/scans?limit&passed_only&run_id` | `services.list_scans()` | direct `ScanResult` query | `scan_results` | Demo **or** live scan | No | **Yes** — `run_id` filtered only if supplied; else newest `as_of` wins (demo can win) |
| **Candidates** | `GET /universe/scans?...&passed_only=true` | `services.list_scans()` | direct `ScanResult` query | `scan_results` | Demo **or** live scan | No | **Yes** — same as Scan |
| **Conviction** | `GET /conviction?symbol&run_id` | `services.list_conviction()` (+ `_explain`) | direct `ConvictionScore` query | `conviction_scores` | Demo **or** live scan | No | **Yes** — newest `as_of` per filter, no demo exclusion |
| **Analogs** | `GET /analogs?symbol&regime&sector&run_id` | `services.analogs()` | `TradeRepository.closed()`, `_latest_scan`, `latest_regime` | `trades`, `scan_results`, `market_regimes` | DB persistence (+ demo seeds trades) | No | **Yes (partial)** — demo *does* seed `trades`; the regime/scan context can also be demo |
| **Trade Plan** | `GET /tradeplan/{symbol}` (+ `/options-eligibility/{symbol}`, `/options-recommendation/{symbol}`) | `tradeplan_service.trade_plan()` | direct `ScanResult`, `latest_conviction/opportunity/regime`, `_candidate_risk_budget`, analog stats | `scan_results`, `conviction_scores`, `market_regimes`, `opportunity_classifications`, `portfolio_snapshots`, `trades` | Demo **or** DB persistence | No | **Yes** — built from latest scan/conviction/regime, which can be demo |
| **Watchlists** | `GET /watchlists`, `/watchlists/dates`, `/watchlists/compare` | `watchlist_service.get_watchlists/...` | `WatchlistRepository.for_date/latest_date` | `watchlist_entries` | Demo (`run_id="demo"`) **or** live (`run_id=None`) | No | **Yes (mitigated)** — generation prefers live (`_winning_batch`), but `get_watchlists(run_id=None)` reads the newest date's rows **without excluding demo** |
| **Portfolio** | `GET /portfolio/snapshots`, `GET /risk/metrics` | `services.list_snapshots/list_risk_metrics` | direct queries | `portfolio_snapshots`, `risk_metrics` | Demo **or** session persistence | No | **Yes** — `run_id` filtered only if supplied; else all runs incl. demo |
| **Analytics** | `GET /performance`, `/performance/attribution`, `GET /trades?status=closed`, `GET /portfolio/snapshots` | `services.performance_summary/attribution/list_trades` | `TradeRepository` | `trades`, `portfolio_snapshots` | Demo **or** persistence | No | **Yes** — aggregates trades across all runs incl. demo unless `run_id` set |
| **Replay** | `POST /actions/replay` (+ `GET /trades`, `GET /conviction`) | `actions.replay_summary()` | `RunRepository`, `TradeRepository`, `AuditLogRepository` | `runs`, `trades`, `audit_log`, `conviction_scores` | Demo **or** persistence | No | **Yes** — `replay` defaults to the *latest* run, which can be the `demo` run |
| **Signal Eval** | `GET /signal-evaluation`, `/signal-evaluation/signals` | `signal_eval_service` | direct ORM joins | `signals`, `trades`, `conviction_scores`, `watchlist_entries` | Demo **or** persistence | No | **Yes** — conviction/watchlist sub-queries pick latest per symbol with no demo exclusion |
| **Signal Audit** | `GET /signal-audit` | `signal_audit_service` | direct ORM joins | `trades`, `conviction_scores`, `scan_results`, `watchlist_entries`, `market_regimes` | Demo **or** persistence | No | **Yes** — trades filter by `run_id`, but conviction/scan/watchlist/regime use global latest-by-symbol |

## Question-by-question answers

**1. Exact endpoint / 2. Service / 3. Repository / 4. Tables** — see the table.

**5. Where does data originate?** For **every** screen: the **Database** (rows
previously written by either the **Demo Seeder** or a **live scan / session**).
**Config** feeds only the scan *action's* inputs. **Cached/Yahoo** data feeds only
the **actions** (`scan`/`refresh-data`/`paper-session`), never a screen read.

**6. Is live market data ever requested?** Not by any screen read. Only by the
**action** endpoints: `run_scan`, `refresh_data`, `paper_session`,
`track_watchlist_performance` (all under `POST /actions/...`). A screen only sees
live data **after** one of those actions has written it to the DB.

**7. Can stale/demo data shadow live data?** **Yes — on every screen except via
the watchlist *generation* path.** The shared cause: read services filter
`run_id` only when one is explicitly supplied, then order by `as_of DESC`. A demo
row dated on/after your last live scan wins. There is **no global "ignore demo"
switch** today.

## Recommendation (drives the next two tasks)

- **Production Data Mode** — a persisted setting that (a) disables the demo
  seeder, (b) purges `run_id="demo"` rows, and (c) makes every read query exclude
  demo rows — so a scan can never display seeded data.
- **Scan pipeline verification** — record per-scan provenance (provider, universe,
  newest bar timestamp, pull time, data age) and surface a **STALE DATA** guard,
  so "fresh data was actually pulled" is provable on the Scan screen.

Both are specified as follow-on work.
