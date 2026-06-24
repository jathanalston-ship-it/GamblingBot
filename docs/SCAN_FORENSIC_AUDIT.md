# Scan Forensic Audit — root-cause report (no code changes)

Reported symptoms: `provider=yfinance, symbols=157, rows=30, live fetch successful`;
yet the scan table shows **6 rows** and conviction / analogs / watchlists are **empty**.

I cannot read your installed app's database from here, so this report (a) traces the
exact code paths with evidence, (b) reproduces the funnel with the real scanner, and
(c) gives you the precise SQL to confirm the numbers on **your** DB.

---

## PART 1 — Forensic runtime audit (where rows disappear)

### The pipeline funnel (code-traced)
```
157 universe symbols  (universe_size)
   │  provider.get_bars per symbol  — failures/empties are skipped (session.pull_bars)
   ▼
N symbols returned data  (symbols_scanned = len(bars) = scan_metadata.symbol_count)
   │  MomentumScanner gate: price>5, $vol, rel-vol, within-ATH, EMA-stack, sector RS
   ▼
P passed candidates  (symbols_passed = scan.candidates)
   │  scan.to_records()  ←★ "passing candidates only" — scan_results stores PASSED ONLY
   ▼
scan_results rows = P            ← the scan table renders these
   │  if STALE → conviction SKIPPED for the WHOLE run  (★ root cause of the empties)
   ▼
conviction_scores = P (fresh) or 0 (stale)
   │  analogs + trade_plans + watchlists are derived from conviction
   ▼
candidate_analogs / trade_plans / watchlist_entries = 0 when conviction = 0
```

**Evidence (code):**
- `universe/screener.py` `to_records()` docstring: *"Rows ready for the `scan_results`
  table (**passing candidates only**)"* — it iterates `self.candidates` and sets
  `passed=True` on every row. ⇒ **`scan_results` never contains failed symbols.**
- `api/actions.py run_scan`: `scan_rows = ScanResultRepository.save_records(scan.to_records(...))`
  and the conviction loop is guarded by **`if not stale:`** — when the pull is stale,
  **zero** conviction rows are written, and the analog/trade-plan/watchlist steps
  (also gated `if not stale and conviction_rows:`) never run.

### Reproduction (real scanner + run_scan, 157 symbols, 30 with data, STALE)
```
universe_size                = 157
symbols_pulled / scanned     = 30        (127 symbols returned no data → skipped)
symbols_passed               = 30        (scan_results rows)
stale                        = True      (data_age_minutes = 18087 ≈ 12.5 days)
conviction_scores_persisted  = 0         ← STALE gate skipped conviction
analogs_persisted            = 0
trade_plans_persisted        = 0
watchlists_generated         = 0
DB counts → scan_results=30, conviction=0, analogs=0, trade_plans=0, watchlist_entries=0
```
This exactly reproduces "conviction/analogs/watchlists empty after a successful live
fetch": **the scan was flagged STALE, so conviction (and everything derived from it)
was skipped.** This is the dominant root cause and is independent of the 6-vs-30 detail.

### SQL to run on YOUR database (deliverables 1–5)
SQLite DB is at `%APPDATA%\Momentum Lab\…\momentum.db` (Windows) or `data/momentum.db`.

```sql
-- latest live scan run_id
SELECT run_id FROM runs WHERE mode='scan' ORDER BY started_at DESC, id DESC LIMIT 1;
-- (call it :run below)

-- 1. row counts for the run
SELECT 'scan_results'      AS tbl, COUNT(*) FROM scan_results      WHERE run_id=:run
UNION ALL SELECT 'conviction_scores',  COUNT(*) FROM conviction_scores  WHERE run_id=:run
UNION ALL SELECT 'candidate_analogs',  COUNT(*) FROM candidate_analogs  WHERE run_id=:run
UNION ALL SELECT 'trade_plans',        COUNT(*) FROM trade_plans        WHERE run_id=:run
UNION ALL SELECT 'watchlist_entries',  COUNT(*) FROM watchlist_entries  WHERE run_id=:run;

-- 2. distinct symbols persisted
SELECT COUNT(DISTINCT symbol) FROM scan_results WHERE run_id=:run;

-- 3/4/5. first 20 symbols in each
SELECT symbol FROM scan_results     WHERE run_id=:run ORDER BY rank      LIMIT 20;
SELECT symbol FROM conviction_scores WHERE run_id=:run ORDER BY score DESC LIMIT 20;
SELECT symbol FROM watchlist_entries WHERE run_id=:run ORDER BY rank      LIMIT 20;

-- provenance: how many of the 157 actually returned bars + staleness
SELECT scan_id, provider, symbol_count, data_age_minutes, stale
  FROM scan_metadata ORDER BY pull_timestamp DESC LIMIT 1;
SELECT COUNT(*) AS fetches,
       SUM(CASE WHEN bar_count>0 THEN 1 ELSE 0 END) AS returned_data
  FROM market_data_provenance WHERE run_id=:run;
```

### Comparison (deliverable 6) — fill from the SQL above
| Stage | Source of number | Expected for your case |
|---|---|---|
| symbols pulled | `runs`/universe = 157 | 157 |
| symbols returned data | `scan_metadata.symbol_count` / `market_data_provenance` `returned_data` | likely **30** |
| symbols passed → persisted | `COUNT(*) scan_results` | **6** (table) or 30 |
| symbols scored | `COUNT(*) conviction_scores` | **0** (stale) |
| symbols displayed | scan table | = `scan_results` count |

**If `COUNT(*) scan_results = 6` and `scan_metadata.symbol_count = 30`:** nothing is lost
on render — `30` is *symbols that returned data*, `6` is *passed candidates*; the table
correctly shows the 6 persisted rows. **If `scan_metadata.stale = 1`:** that is why
conviction/analogs/watchlists are empty.

---

## PART 2 — Scan table renderer audit

Both the provenance "Rows" field **and** the table read `scan_results` for the **same**
active run via `resolve_active_run_id` — so they cannot legitimately disagree from one DB.

| # | Question | Answer (code evidence) |
|---|---|---|
| 1 | Does the API return 30 rows? | `GET /universe/scans?limit=300` → `list_scans(run_id=active, passed_only=False, limit=300)` returns **all** `scan_results` for the active run. It returns exactly `COUNT(*) scan_results` (≤300). |
| 2 | Does the frontend receive them? | Yes — `useApi<ScanResult[]>(path)` stores the full array as `all`; the count shown is `rows.length`. |
| 3 | Does the frontend filter rows? | Only by **sector** (`sector==="all"` default → no filter) and re-sorts. `Scan.tsx`: `rows = all.filter(sector)`.  **A non-"all" sector selection would reduce the visible count.** |
| 4 | Pagination? | **No.** No page/offset; `limit=300` ceiling only. |
| 5 | Virtualization truncating? | **No.** Plain `rows.map(...)` over a `<table>`; no windowing. |
| 6 | Hidden pass-only filter? | `passed_only` is sent only on the `/candidates` route (`shortlist`) or the explicit "passed only" checkbox. **Irrelevant here** — `scan_results` is already passed-only, so it never reduces the count. |
| 7 | Stale state from a previous run? | The table calls `reload()` + `reloadMeta()` in the Run-scan `onDone`. The provenance panel **polls every 60 s** (`refreshMs: 60_000`) while the table only refetches on mount/reload — so the **banner can lead the table by up to ~60 s** if the panel refreshes to a newer run before the table reloads. This is the one place a transient "30 (banner) vs 6 (table)" could appear. |

**Render pipeline log to capture (DevTools / add temporary `console.log`):**
```
rows from API       = data.length            // = COUNT(*) scan_results for active run
rows after transform= all.length             // identical (no transform drops rows)
rows after filter   = rows.length            // < all.length ONLY if a sector ≠ "all" is selected
rows rendered       = document.querySelectorAll('tbody tr').length
```
**Most likely renderer verdict:** no truncation — the table shows the true `scan_results`
count for the active run. The "30" you saw is a **different funnel metric** (symbols
scanned / symbol_count), not the table's row source. Confirm with `COUNT(*) scan_results`.

---

## PART 3 — Conviction generation audit (per candidate)

**Conviction is all-or-nothing per run — there is no per-candidate rejection.**
`run_scan` (`api/actions.py`):
```python
if not stale:
    for c in candidates:                 # EVERY candidate is scored
        conviction_rows.append(ConvictionScore.from_result(...))
# else: conviction_rows stays empty for the WHOLE run
```
So for the latest run, every candidate has the **same** status:

| symbol | scan_score (momentum) | conviction_status | failure_reason |
|---|---|---|---|
| every candidate | (its `momentum_score`) | **NOT GENERATED** | scan flagged **STALE** (`scan_metadata.stale=1`, `data_age_minutes > 5760` = 4-day threshold) → `run_scan` skips conviction for the entire run |

(If your SQL shows `stale=0` but conviction is still 0, that would instead point to an
exception during the conviction step — check the run’s logs / `runs.status`. But the
empty-analogs + empty-watchlists combination is the classic stale signature.)

**Summary (fill from SQL):**
- total scanned (`symbol_count`) = ____ (likely 30)
- total persisted (`COUNT scan_results`) = ____ (the table count, e.g. 6)
- total conviction generated (`COUNT conviction_scores`) = **0** ⇐ stale gate

---

## Root cause (one line)
The latest scan was **flagged STALE** (newest bar older than the 4-day threshold), so
`run_scan` **skipped conviction generation** for the entire run — and analogs, trade
plans and watchlists are all derived from conviction, hence empty. The scan table’s
"6" is the count of **passed candidates** persisted to `scan_results` (passed-only by
design); the "30" is a different funnel stage (**symbols that returned data**), not the
table’s row source — no rows are lost on render. Run the SQL above to confirm
`scan_metadata.stale` and the exact `scan_results` count.

## Why it’s stale (next step, not patched)
yfinance daily bars over a weekend/holiday, an intraday run before the session bar
exists, or `MRP_STALE_AFTER_MINUTES` set too tight. The fix (when you approve) is to
decide the staleness policy — e.g. treat the most recent *completed trading day* as
fresh, or relax the threshold — and/or surface the STALE banner more prominently on the
Conviction/Watchlist screens.
