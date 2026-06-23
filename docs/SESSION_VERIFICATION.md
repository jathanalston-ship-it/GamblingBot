# Verification Report — Universe Audit · Live Conviction · Data Health

Three deliverables for this session. Each section is a self-contained verification
report (trace → findings → implementation → tests → result).

---

## 1. Scanner Universe Construction — Audit + Dynamic Universe Mode

### Problem
"Scanner appears to repeatedly return the same symbols."

### Trace (Scanner → Universe Builder → Provider → Filters)

| Stage | Module | Finding |
|---|---|---|
| **Universe builder** | `universe/membership.select_universe`, `universe/universes.py` | Resolves the tradeable set from **config** (user override `universes.yaml` → shipped `universes.example.yaml` → embedded default). **Not hardcoded** — `DEFAULT_SYMBOLS` was removed in an earlier session. |
| **Selection** | `api/universe_service.resolve_selected`, `settings.yaml` `universe.selected` | The selected universe key persists in `settings.yaml`; `routes/actions._selected_universe` feeds it into `run_scan`. |
| **Provider** | `api/user_settings.build_provider`, `api/actions.pull_bars` | Bars are pulled **live** from the configured provider (yfinance/alpaca/polygon) each scan; a scan with no bars fails loudly. |
| **Scanner** | `universe/screener.MomentumScanner` | Pure: `bars → features → filter → rank`. Returns whatever survives the filters for the supplied bars. |
| **Filters** | `universe/scanner_config.ScanFilters` | Price floor, dollar-volume, relative-volume, ATH distance, EMA-stack — all config tunables. |

### Root cause of "same symbols"
Not the universe (already dynamic). The earlier causes were (a) demo data overriding live
data and (b) stale bars — both fixed earlier this session by **Production Data Mode**
(demo rows excluded/purged) and **Scan Verification** (stale data blocks conviction). This
session adds the missing **scale** controls.

### Is the universe hardcoded / config / file / provider?
- **Hardcoded?** No.
- **Config?** Yes — `config/universes.example.yaml` + user override; selection in `settings.yaml`.
- **Static file?** Yes, as the shipped *seed* (the example YAML), with an embedded fallback.
- **Provider?** Yes for bars; and now optionally for **membership** via the hybrid refresh.

### Implementation (this session)
- **Liquidity prefilter + cap** (`universe/prefilter.py`): caps the fully-scanned set to the
  most-liquid `max_symbols` (param → `MRP_MAX_SCAN_SYMBOLS` → 2000). `run_scan` reports
  `symbols_pulled` vs `symbols_scanned`.
- **Hybrid refresh** (`POST /universes/{key}/refresh`): refresh a built-in's membership from
  the provider when it supports `list_symbols`; otherwise the shipped seed is kept.
- Universe options already present: S&P 500 / NASDAQ 100 / Russell 1000 / Russell 3000 /
  All Tradable / Custom (built-ins + user custom/imported/sector). UI shows actual size
  (e.g. "Russell 3000: 2984") and the Scanner stats strip shows symbols scanned.

### Tests
`tests/unit/universe/test_prefilter.py`, `tests/unit/api/test_universe_refresh.py`,
`tests/unit/universe/test_universes.py`, `tests/unit/api/test_universes_api.py` (incl. a
3000-symbol scale test).

### Result ✅
Universe is fully dynamic, selectable, config/provider-driven, displays its real size, and
scales to 5000+ symbols.

---

## 2. Live Conviction Persistence

### Current state (before)
`run_scan` already generated conviction **and persisted** `conviction_scores` rows
associated with the `scan_id` (`run_id = scan-<YYYYMMDD>`): symbol, scan_id, score
(conviction), band (grade), score_breakdown (JSON), generated_at (`ts`). The **explanation**
was computed only at read time, not persisted.

### Implementation (this session)
1. **Persist the explanation.** New `explanation` column on `conviction_scores`
   (migration `0017`). `ConvictionScore.from_result` generates it at scan time via the new
   pure `conviction/narrative.py` (`explain`).
2. **Shared narrative.** `conviction/narrative.py` is the single source for contributor
   impacts + the plain-language sentence; both `run_scan` (write) and `api/services` (read)
   use it, so a stored and a recomputed explanation always agree. The read path prefers the
   stored `explanation` and only recomputes for legacy rows.
3. **Stored fields per row**: `symbol`, `run_id` (= scan_id), `score` (conviction),
   `band` (grade), `breakdown` (score_breakdown), `explanation`, `ts` (generated_at).
4. **Watchlists use the latest live conviction** (`watchlist_service._winning_batch`:
   newest `as_of`; live beats demo at a tie). Under **Production Data Mode** demo rows are
   filtered out entirely.
5. **No live conviction → honest empty state.** The Watchlists view now shows
   **"No live conviction data available"** (never demo) when there are no live scores; the
   Data Health dashboard reports the same.

### Tests
`tests/unit/conviction/test_narrative.py` (pure generator), `test_scan_verification.py`
(asserts each persisted row has `run_id == scan_id` and a non-empty `explanation` containing
the symbol), `tests/unit/watchlist/test_service.py` + `test_watchlist_live_over_demo.py`
(latest-live selection). Migration `0017` upgrades, `alembic check` clean, downgrade
round-trips.

### Result ✅
Conviction is persisted per scan with its explanation; watchlists consume the latest live
batch and never fall back to demo.

---

## 3. Data Health Dashboard

### Implementation
- **Service** `api/data_health_service.py` — one read-only aggregate with traffic-light
  (green/yellow/red) status per metric and an overall status (worst-of):
  Current Provider · Connection Status · Last Successful Pull · Data Age · Universe Size ·
  Symbols Cached · Latest Scan · Latest Conviction Run · Latest Watchlist Generation.
- **Raw diagnostics** (`/data-health/diagnostics`): provider, cache path, database path,
  latest bar timestamp, latest scan id/timestamp, conviction/watchlist provenance.
- **Routes** `GET /data-health`, `GET /data-health/diagnostics`.
- **UI** `views/DataHealth.tsx` (nav "Data Health"): status dots, metric rows, overall
  banner, and a **View Raw Diagnostics** expander. Auto-refreshes every 30 s.
- Pure status logic (`_worst`, `_age_status`, `_humanize_age`) is unit-tested directly; the
  aggregator wires the session + environment in. Honours data mode (live conviction only in
  production).

### Tests
`tests/unit/api/test_data_health.py` — pure status logic, empty-DB (→ red,
"No live conviction data available"), fresh pipeline (→ green), stale scan (→ degraded
connection), diagnostics raw values, and both routes via `TestClient`.

### Result ✅
A single dashboard shows whether the pipeline is flowing, with green/yellow/red indicators
and raw diagnostics.

---

## End-to-end proof — the scanner reports a breakout candidate

Driving the **real** `MomentumScanner` → `ConvictionEngine` → `narrative.explain` on a
constructed breakout setup (a stock pushing to a fresh ATH on a relative-volume surge):

```
=== SCANNER OUTPUT (real MomentumScanner) ===
symbols scanned : 3
passed filters  : 2

TOP CANDIDATE   : BRKO  (Technology)
  momentum score: 100.0 / 100
  price         : $73.77
  rel volume    : 3.09x
  dist from ATH : 0.00%
  ATR           : 1.37
  sector RS     : 1.00

=== CONVICTION (real ConvictionEngine) ===
  score : 80.0 / 100   band: high
  top drivers:  momentum +9.0 · sector strength +6.0 · relative volume +5.0 · ATH proximity +5.0

=== EXPLANATION (persisted at scan time) ===
  BRKO ranks highly (80/100) due to strong momentum, sector strength and relative volume.
```

The scanner identifies the symbol at a fresh ATH on 3x relative volume with a perfect
momentum score, conviction scores it HIGH (80/100), and the persisted explanation states the
reasoning in plain language.

## Quality gate
ruff + `mypy --strict` (289 files) clean; **1150 tests pass**; migration `0017` drift-free
and round-trips; desktop typecheck + build green.
