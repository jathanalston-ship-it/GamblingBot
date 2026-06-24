# End-to-End Functionality Audit (diagnosis only — no code changes)

**Build:** branch `claude/vigilant-wozniak-oueczq`, version 0.0.67.
**Method:** code trace + a real-universe simulation (`scratchpad/e2e_audit.py`) over the
shipped 96-symbol default universe (`AAPL, MSFT, NVDA, …`), offline provider standing in
for live Yahoo. Proof, not assumptions.

## 1–2. Execution path + per-screen sources

| Screen | API endpoint | Service | Tables READ | Tables WRITTEN | Market-data source | Conviction source | Analog source |
|---|---|---|---|---|---|---|---|
| **Run Scan** | `POST /actions/scan` | `actions.run_scan` | `scan_metadata`, `runs`, `trades` (analog cohort) | `scan_results`, `conviction_scores`, `market_regimes`, `scan_metadata`, `runs`, **`trade_plans`**, **`candidate_analogs`**, `watchlist_entries` | **live provider** (`pull_bars`→`YahooProvider.get_bars`, network, **no cache**) | computed by `ConvictionEngine` | `trades` (all closed history) |
| **Candidates / Scan** | `GET /universe/scans` | `services.list_scans` | `runs` (`resolve_active_run_id`), `scan_results` | none | — | — | — |
| **Conviction** | `GET /conviction` | `services.list_conviction` | `runs`, `conviction_scores` | none | — | `conviction_scores` | — |
| **Analogs** | `GET /analogs` | `services.analogs` | **`trades`** (closed, all history), `scan_results`, `market_regimes` | none | — | — | **`trades`** (NOT `candidate_analogs`) |
| **Watchlists** | `GET /watchlists` | `watchlist_service.get_watchlists` | `runs`, `watchlist_entries` | none | — | `conviction_scores` (at generation) | — |
| **Trade Plans** | `GET /tradeplan/{sym}` | `tradeplan_service.trade_plan` | **`scan_results`**, `conviction_scores`, `market_regimes`, `trades`, `portfolio_snapshots` | none | — | `conviction_scores` | `trades` |
| **Options Rec.** | `GET /options-recommendation/{sym}` | `options_recommendation_service` | `scan_results`, `market_regimes`, `portfolio_snapshots` (+ recomputes trade plan) | none | — | via trade plan | `trades` |

## 3–4. Simulation counts (run_id `scan-20260624`, 96-symbol universe, not stale)

```
count(scan_results)      = 70
count(conviction_scores) = 70
count(candidate_analogs) = 70
count(trade_plans)       = 70
count(watchlist_entries) = 30
count(trades [history])  =  0   <- the Analogs panel's actual source
```
Every read endpoint returned live data pinned to `scan-20260624` (verified `run_id` on all
70 scan rows + all 70 conviction rows). Watchlists = 30 (top-10 × 3 horizons). Options:
15/15 probed candidates returned a recommendation.

## 5. Screens that can still be empty / demo / stale / cached

| Risk | Screen | Verdict | Evidence |
|---|---|---|---|
| **demo** | all | **No** — once a live scan exists, `resolve_active_run_id` pins every read to `runs.mode=="scan"`; demo only surfaces when **no** live scan has run. | counts above: all live `run_id`, demo untouched |
| **stale** | Conviction, Watchlists, Trade Plan, Options | **Yes, by design** — if the pull is stale, `run_scan` skips conviction (`if not stale:`), so these are empty until fresh data. Surfaced honestly ("STALE" badge, "No live conviction data available"). | prior `stale_probe`: conviction 0, watchlists 0 |
| **cached** | none (scan path) | **No** — the scan calls `provider.get_bars` live every run; it never reads `BarCache`. | `docs/` data-freshness audit |
| **empty despite success** | **Analogs** | **YES** — see §7 | simulation: `/analogs?symbol=UNP → sample_size=0, trades=0` after a fully successful scan |
| empty (per-symbol) | Options Rec. | Expected — a 404 means "Shares Preferred / not options-eligible", not a failure. | 15/15 eligible here, but ineligible symbols 404 legitimately |

## 6. Summary table

| Screen | Data Source | Live? | Persisted? | Can Be Empty? | Reason |
|---|---|---|---|---|---|
| Scan / Candidates | `scan_results` | ✅ | ✅ | No (after success) | written every scan, run-scoped |
| Conviction | `conviction_scores` | ✅ | ✅ | Only if **stale** | gated off when data is stale |
| Watchlists | `watchlist_entries` | ✅ | ✅ | Only if **stale** | generated from live conviction |
| Trade Plans | recomputed from `scan_results` (+conviction/regime) | ✅ | ⚠️ written but **not read** | No (needs price+ATR, always present) | `/tradeplan` recomputes; ignores `trade_plans` table |
| **Analogs** | **`trades`** (historical closed trades) | ✅ (but trade-derived) | ⚠️ written but **not read** | **YES** | depends on **trade history**, not the scan |
| Options Rec. | recomputed from `scan_results`+eligibility | ✅ | ❌ (never persisted) | Per-symbol (404 = shares-preferred) | eligibility gate, by design |

## 7. Why a screen can still be empty after a successful scan — **Analogs**

**Stopping here as requested.** After a fully successful scan (70 candidates, 70 conviction,
70 trade plans, 70 persisted analog rows), the **Analogs panel is empty** (`sample_size = 0`,
`trades = []`).

**Root cause — the read path does not use the scan's output:**

1. The `/analogs` endpoint and the candidate inspector's analog block call
   `services.analogs`, whose cohort is `TradeRepository.closed(None)` — i.e. the **`trades`
   table** (historical *closed trades*). On a fresh install `count(trades) = 0`, so the
   cohort is empty regardless of how good the scan was. Analogs answer "how did *past trades*
   in this regime+sector behave?", which is structurally independent of the current scan.

2. This is **not** demo, stale, or cached data — it is a genuine empty state caused by **no
   trade history yet**. There is nothing to be analogous *to*.

3. **Compounding architectural finding:** the scan now persists `candidate_analogs` (70 rows)
   and `trade_plans` (70 rows), but **no UI endpoint reads them** — `/analogs` reads `trades`
   and `/tradeplan` recomputes from `scan_results`. The persisted tables are currently
   consumed **only** by `provenance_service` for row counts. So the "70 analog rows" do **not**
   feed the Analogs panel; the panel still shows 0. Write path and read path disagree.

**Net:** Scan, Candidates, Conviction, Watchlists, Trade Plans and Options all populate from a
single successful live scan. **Analogs is the one screen that can be empty after a successful
scan**, because its data source is the (initially empty) `trades` table rather than the scan —
and the newly-persisted `candidate_analogs` rows that *would* fix this are not read by the
endpoint. No fix applied (diagnosis only).
