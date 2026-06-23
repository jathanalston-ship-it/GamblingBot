# Live research pipeline (Run Scan → Watchlists)

The end-to-end path that turns **live market data** into actionable watchlists,
so the desktop app stops showing the demo handful of tickers once a real scan has
run. This document is the architecture, the data-flow contract, and the
verification checklist for that pipeline.

## The problem it fixes

Watchlists rank the universe from the **`conviction_scores`** table. Before this
change, only the **demo seeder** wrote that table; a live "Run Scan" persisted
only `scan_results`. So no matter how often you scanned live, the watchlists were
permanently driven by the ~8 demo example tickers (AAPL/MSFT/NVDA/…). The fix
makes a live scan persist **conviction scores** (plus the regime and run
metadata), and makes the watchlist resolver prefer the **newest live batch** over
the demo seed.

## Architecture

```
                       ┌─────────────────────────────────────────────┐
   Run Scan  ──────▶   │  actions.run_scan  (the live pipeline)       │
   (button / API /     │                                              │
    CLI / job)         │  1. select_universe()      ← config, not     │
                       │       (symbols, sectors)     hardcoded       │
                       │  2. pull_bars(universe + SPY)  ← Yahoo        │
                       │  3. MomentumScanner.scan()  → ranked cands    │
                       │  4. RegimeEngine.evaluate(SPY, breadth)       │
                       │  5. ConvictionEngine.score() per candidate    │
                       │                                              │
                       │  Persist (one transaction, idempotent):       │
                       │   • scan_results       (ScanResultRepository) │
                       │   • conviction_scores  (delete+insert by run) │
                       │   • market_regimes     (delete+insert by key) │
                       │   • runs               (RunRepository)        │
                       └───────────────────────┬──────────────────────┘
                                               │  run_id = scan-YYYYMMDD
                                               ▼
   Generate Watchlists ─▶  watchlist_service._load_candidates()
                              │  picks the NEWEST conviction batch:
                              │   newest as_of wins; at a tie LIVE beats demo
                              ▼
                           WatchlistEngine → watchlist_entries
                              ▼
                           Today / This Week / This Month  (desktop view)
```

### Universe selection (`src/momentum/universe/membership.py`)

`select_universe() -> (symbols, {symbol: sector})` resolves the tradeable set from
configuration — user override (`<MRP_USER_DIR>/config/universe_symbols.yaml`) →
shipped `config/universe_symbols.example.yaml` → in-code embedded default (96
large-cap US equities across 11 GICS sectors). **No action hardcodes symbols.**
The old `DEFAULT_SYMBOLS = [8 mega-caps]` is gone; the CLI `--symbols` flag now
defaults to this universe when empty.

### The scan pipeline (`src/momentum/api/actions.py::run_scan`)

| Step | What it does | Persists |
|---|---|---|
| 1 | Pull live bars for the universe **and** SPY (regime benchmark) | — |
| 2 | `MomentumScanner.scan(bars, sectors)` → ranked candidates; `as_of` = the data date; `run_id = scan-<YYYYMMDD>` | — |
| 3 | `RegimeEngine.evaluate(SPY, breadth=…)` where breadth = % of the universe above its 200DMA (computed live) | — |
| 4 | `ConvictionEngine.score()` per candidate (regime label, sector RS, rel-volume, distance-to-ATH, breadth, momentum) | — |
| 5 | save scan candidates | `scan_results` |
| 6 | replace conviction for `run_id`, insert scored rows | `conviction_scores` |
| 7 | replace regime for `(as_of, benchmark, model_version)`, insert | `market_regimes` |
| 8 | `RunRepository.start(…).complete(…)` — run lifecycle/metadata | `runs` |

All writes share one transaction and commit together. Re-running the same day is
**idempotent**: the stable `run_id` + delete-then-insert means rows are replaced,
never duplicated (verified by a test).

### Watchlist resolution (`src/momentum/api/watchlist_service.py`)

`_load_candidates` no longer just takes "the latest `as_of`". It selects the
**winning batch**:

1. newest `as_of` across all conviction rows wins;
2. at an identical `as_of`, any **live** run (`run_id != "demo"`) beats the demo
   seed;
3. within that one `(as_of, run_id)` batch, the most-recently-written row per
   symbol is authoritative.

This is the guarantee **"demo data never overrides newer live data"**, expressed
in the read path so it holds no matter what is in the table.

## Data-flow guarantees

- **No placeholders / no demo-only paths**: the same `run_scan` runs for every
  caller (desktop button, `POST /actions/scan`, CLI, jobs). The demo seeder is a
  separate, explicitly-invoked path; nothing in the live path depends on it.
- **No hardcoded symbols**: every entry point resolves the universe from config.
- **Idempotent**: stable daily `run_id`; all four surfaces replace-by-key.
- **Self-consistent dates**: scan, conviction and regime all key off the same
  data date (`scan.as_of`), so they join cleanly.

## Verification checklist

Run `make test` (full suite) — the automated coverage below all passes. Manual UI
checks use the desktop **Scanner**, **Watchlists** and **Command Center** views.

| Scenario | Expectation | Covered by |
|---|---|---|
| **Fresh install** (empty DB) | Scan persists scan_results + conviction + regime + run; watchlists then populate from live symbols. Watchlists on an empty DB return empty (no crash). | `test_actions.py::test_run_scan_persists_results`, `test_watchlist_live_over_demo.py::test_empty_database_yields_empty_watchlists` |
| **Demo database** (demo only, no live scan) | Watchlists show the demo seed (nothing live to prefer). | `test_watchlist_live_over_demo.py::test_demo_only_when_no_live_scan` |
| **Live database** (live scan, no demo) | Watchlists rank the live candidates from the scan's conviction scores. | `test_run_scan_persists_results` + watchlist generation |
| **Mixed database** (demo + newer live scan) | Live wins by date; demo never shown. | `test_watchlist_live_over_demo.py::test_newer_live_scan_overrides_older_demo` |
| **Mixed, same date** (demo + live at identical `as_of`) | Live wins the tie. | `test_watchlist_live_over_demo.py::test_live_beats_demo_at_same_date` |
| **Re-run idempotency** | Scanning twice in a day replaces, never duplicates. | `test_actions.py::test_run_scan_is_idempotent_per_day` |
| **Universe is config-driven** | `select_universe()` returns 90+ symbols across 8+ sectors; user override respected; shipped YAML matches the embedded default (drift guard). | `tests/unit/universe/test_membership.py` |

### Manual smoke (desktop)

1. **Reset → Load Demo Data**, open **Watchlists** — note the demo tickers.
2. **Settings → Data Provider** = yfinance.
3. **Scanner → Run Scan**, wait for the job to complete (result shows
   `candidates`, `regime`, `conviction_scores_persisted`).
4. **Watchlists → Generate** — the lists now rank the **live** scan's symbols, not
   the demo handful. The `as_of` is today's data date.

## Files

- `src/momentum/universe/membership.py` — universe selection.
- `config/universe_symbols.example.yaml` — the shipped default universe.
- `src/momentum/api/actions.py` — `run_scan` (the pipeline) + `_breadth_above_200dma`.
- `src/momentum/api/routes/actions.py` — `_universe()` wiring (no hardcoded list).
- `src/momentum/api/watchlist_service.py` — newest-batch resolution.
- `src/momentum/cli/main.py` — `--symbols` defaults to the configured universe.
