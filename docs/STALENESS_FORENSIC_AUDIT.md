# Staleness + Funnel + Scan-Metric Forensic Audit (read-only, no code changes)

Three forensic audits of the latest scan. I cannot read your installed app's
SQLite from here, so for the per-run *values* I give the exact SQL to run on your DB
(`%APPDATA%\Momentum Lab\…\momentum.db`); for the *logic* I quote the exact code.

---

## AUDIT 1 — The staleness decision

### 1.1 Read the exact values (run on your DB)
```sql
-- latest live scan
SELECT run_id FROM runs WHERE mode='scan' ORDER BY started_at DESC, id DESC LIMIT 1;  -- :run
-- the five values
SELECT scan_id, stale, data_age_minutes, bar_timestamp, pull_timestamp
  FROM scan_metadata WHERE scan_id = :run;
```
`MRP_STALE_AFTER_MINUTES`: check your environment (`echo %MRP_STALE_AFTER_MINUTES%`);
if unset, the code default below applies.

### 1.2 The exact boolean expression that sets stale (`api/actions.py:297-306`)
```python
pull_timestamp = dt.datetime.now(tz=dt.UTC)               # now, UTC
bar_timestamp  = _newest_bar_timestamp(bars)              # newest bar across frames, UTC
threshold      = _stale_threshold(stale_after_minutes)    # env MRP_STALE_AFTER_MINUTES, else 5760
if bar_timestamp is None:
    data_age_minutes = None
    stale = True                                          # cannot prove freshness
else:
    data_age_minutes = round((pull_timestamp - bar_timestamp).total_seconds() / 60.0, 1)
    stale = data_age_minutes > threshold                  # ←★ THE expression
```
Threshold default: `DEFAULT_STALE_AFTER_MINUTES = 4 * 24 * 60 = 5760` (4 days).

### 1.3 Manual calculation
`data_age_minutes = (pull_timestamp − bar_timestamp) / 60s`, `stale = data_age_minutes > 5760`.

Worked example — **scan on a Tuesday after a Monday market holiday** (the common trip):
- newest bar = last completed session = **Friday 13:30 UTC** (US-equity daily open)
- pull = **Tuesday 14:00 UTC**
- age = Fri 13:30 → Tue 14:00 = 4 days 0h 30m = **5790 min**
- `5790 > 5760` → **stale = True** (by 30 minutes)

Plug your actual values: `(pull_timestamp − bar_timestamp)` in minutes, compare to 5760.

### 1.4 What the "newest bar" represents
Because `run_scan` pulls with `end = _today()` → `period2 = today 00:00 UTC`, **today's
session bar is excluded** (it opens ~13:30 UTC, after the boundary). So the newest bar is
always the **most recent *completed* session strictly before today (UTC)** — never the
current session. Concretely:
- normal weekday → **previous completed trading day** (~1 day old)
- Monday/after-weekend → **last Friday** (~3 days old)
- after a multi-day holiday closure → the **last trading day before the closure** (≥4 days)

`_newest_bar_timestamp` takes the **max** over all universe frames, so it is the *freshest*
symbol's last bar — one fresh symbol keeps the whole scan fresh. (Read your real value:
`bar_timestamp` in the SQL above; e.g. `2026-06-19 13:30:00+00` = that Friday's session.)

### 1.5 Why was the data rejected? (A–E)
| Cause | Verdict | Evidence |
|---|---|---|
| **A) Yahoo failed** | **Ruled out as the trigger** | a total failure yields `bars == {}` → `raise RuntimeError` (`actions.py:273`), the scan errors, it does **not** silently flag stale. Partial failures don't cause stale (`_newest_bar_timestamp` takes the **max**, so any one fresh symbol wins). |
| **B) Market closed** | **Likely** | the newest bar is the previous completed session; a long weekend / holiday pushes it ≥4 days back, crossing 5760. |
| **C) Threshold too strict** | **Likely (contributing)** | the "exclude today" boundary means the freshest possible data is *yesterday*; a 4-day threshold is then tripped by a single Monday holiday (5790 > 5760). The threshold is borderline for the boundary design. |
| **D) Timezone bug** | **Ruled out** | `normalize_bars` forces tz-aware **UTC** (`schema.py:157-161`); `_newest_bar_timestamp` localizes any naive ts to UTC; `pull_timestamp` is `now(tz=UTC)`. The subtraction is UTC−UTC — no offset error. |
| **E) Timestamp parsing bug** | **Ruled out** | Yahoo epochs parsed `pd.to_datetime(unit="s", utc=True)`; `normalize_bars` **sorts ascending** (`schema.py:174`), so `frame.index[-1]` is genuinely the newest bar. No mis-sort, no off-by-row. |

**Conclusion:** the staleness math is correct; if `stale=1`, the freshest universe bar is
genuinely > 4 days old — i.e. **B (extended market closure) interacting with C (a 4-day
threshold + the exclude-today boundary)**, not a code bug. Confirm by reading `bar_timestamp`:
if it is a legitimate recent trading session (e.g. last Friday), it's B/C; if it is implausibly
old or malformed, re-open D/E.

### 1.6 Exact code path proving conviction was skipped (`api/actions.py:322-342`)
```python
conviction_rows: list[ConvictionScore] = []
if not stale:                                  # ←★ stale True ⇒ this block is skipped
    for c in candidates:
        ... conviction_rows.append(ConvictionScore.from_result(...))
# conviction_rows stays [] when stale
```
And the persistence + downstream (`actions.py` later):
```python
session.add_all(conviction_rows)               # adds 0 rows when stale
...
if not stale and conviction_rows:              # analogs + trade plans + watchlists
    scan_artifacts.persist_artifacts(...)      #   ← skipped
    watchlist_service.generate_watchlists(...) #   ← skipped
```
⇒ `conviction_scores = candidate_analogs = trade_plans = watchlist_entries = 0`.

---

## AUDIT 2 — End-to-end reconciliation (where each count drops)

| Stage | Count source | Drop reason | Code path | Per-symbol reason persisted? |
|---|---|---|---|---|
| Universe symbols | selected universe (config) | — | `universe/membership.select_universe` | n/a (config) |
| Bars returned | `market_data_provenance` rows w/ `bar_count>0` | provider error / empty response → symbol skipped | `orchestration/session.pull_bars` try/except (`continue`) | **Yes** — `market_data_provenance.bar_count = 0` flags the symbols that returned nothing |
| Scanner candidates = Passed | `scan.candidates` | failed a gate: price>5, $-volume, rel-vol, within-ATH, **EMA-stack**, sector-RS | `universe/screener` `_filter` → `FilterReport`; `features["passed"] = report.passed` | **NO — flag** (see below) |
| scan_results rows | `COUNT scan_results` | none (passed ⇒ persisted 1:1) | `scan.to_records()` (passed-only) → `ScanResultRepository.save_records` | yes (these are the survivors) |
| conviction rows | `COUNT conviction_scores` | **STALE** → whole-run skip | `actions.py:326 if not stale` | uniform reason: stale |
| analog / trade_plan / watchlist rows | their `COUNT`s | derived from conviction → 0 when conviction 0 | `actions.py if not stale and conviction_rows` | uniform reason: no conviction |

### ⚠ Flagged: the **scanned → passed** drop has no persisted per-symbol reason
The scanner computes a `FilterReport` with the failing gate per symbol, but only `passed=True`
rows are written to `scan_results` (`to_records()` = "passing candidates only"). **Failed
symbols and their rejection reasons are discarded after the scan** — you cannot reconstruct
"why symbol X was dropped" from the database. This is a **diagnostic gap** (not a correctness
bug: the drop is intentional and gate-explained), but it means the funnel's biggest drop is
not auditable post-hoc. To see those reasons you must re-run the scan and inspect
`scan.filter_report.reasons` (in memory) — it is not stored.

### First-25 symbols per stage (run on your DB)
```sql
-- universe (returned data), newest-bar per symbol
SELECT symbol, bar_count, bar_timestamp FROM market_data_provenance
  WHERE run_id=:run ORDER BY symbol LIMIT 25;
-- symbols that returned NO data (the universe→bars drop)
SELECT symbol FROM market_data_provenance WHERE run_id=:run AND bar_count=0 ORDER BY symbol LIMIT 25;
-- passed → persisted
SELECT symbol, rank, momentum_score FROM scan_results WHERE run_id=:run ORDER BY rank LIMIT 25;
-- conviction (empty if stale)
SELECT symbol, score FROM conviction_scores WHERE run_id=:run ORDER BY score DESC LIMIT 25;
-- watchlist (empty if stale)
SELECT symbol, horizon, rank FROM watchlist_entries WHERE run_id=:run ORDER BY rank LIMIT 25;
```
The `scanned → passed` removed-symbol list is **not** queryable (the flagged gap above).

---

## AUDIT 3 — Scan-page metrics: which funnel stage is each number?

The Scan page renders **four** counts from **three different sources** — proof that the
numbers are different funnel stages, not the same quantity:

| UI label (where) | Endpoint | DB query / field | Frontend component → state | Computation | Funnel stage |
|---|---|---|---|---|---|
| **size = 157** | scan job result | `run_scan` returns `universe_size` | `Scan.tsx` `scanStats.universe_size` | `len(symbols)` (selected universe) | **Universe** |
| **symbols = 30** | `GET /universe/scan-metadata` | `scan_metadata.symbol_count` | `Scan.tsx` `meta.symbol_count` (`useApi`) | `symbol_count = len(bars)` (`actions.py:379`) | **Bars returned** |
| **scanned = 30** | scan job result | `run_scan` returns `symbols_scanned` | `Scan.tsx` `scanStats.symbols_scanned` | `len(bars)` | **Bars returned** (same as above) |
| **passed = 6** | scan job result | `run_scan` returns `symbols_passed` | `Scan.tsx` `scanStats.symbols_passed` | `len(scan.candidates)` | **Passed gate** |
| **Rows (Provenance) = 6** | `GET /provenance` | `screens.scan.rows = COUNT(scan_results WHERE run_id=active)` | `ProvenancePanel` `screens["scan"].rows` | SQL COUNT | **Persisted (=passed)** |
| **candidate table = 6** | `GET /universe/scans?limit=300` | `list_scans(run_id=active, passed_only=False)` rows | `Scan.tsx` `data` → `rows.length` | array length (sector-filtered) | **Persisted (=passed)** |

### Is the UI mixing funnel stages? — **YES, provably.**
- **Symbols: 157** = the *universe size* (`scanStats.size`).
- **Rows: 30** = the *bars-returned* count (`scan_metadata.symbol_count` / `scanStats.scanned`) —
  i.e. how many of the 157 actually returned data. **It is labelled "symbols" / "scanned",
  not "Rows"** in the scan strips; the only field literally labelled **"Rows"** is the
  ProvenancePanel, and that one equals `COUNT(scan_results)` = **6**, *not* 30.
- **Candidate table count: 6** = *passed candidates* persisted to `scan_results`.

So the three numbers you read are **three distinct funnel stages** —
`universe(157) → returned-data(30) → passed(6)` — displayed side by side. They are **not**
the same quantity measured inconsistently; each is correct for its own stage. There is **no
row loss between the API and the table**: the ProvenancePanel "Rows" and the table both equal
`COUNT(scan_results)` for the active run (the table only further narrows if you pick a sector
≠ "all"). The apparent "30 vs 6" is the universe→returned-data→passed funnel, not a render bug.

### To prove it on your screen
- The Stale banner reads `meta.stale` (red strip, "conviction not generated — data too old").
  **If it is red, Audit 1 is your answer.**
- `COUNT(scan_results) WHERE run_id=:run` should equal **both** the table row count **and** the
  ProvenancePanel "Rows" value. If they differ, capture: `data.length` (table) vs the
  `/provenance` `screens.scan.rows` value vs `COUNT(scan_results)` — any mismatch there (and
  only there) would be a genuine render/run-pinning bug.

---

## Bottom line
1. **Staleness math is correct** (no tz/parsing bug). `stale=1` ⇒ the freshest universe bar is
   genuinely > 4 days old — an extended market closure (B) tripping a tight 4-day threshold +
   the exclude-today boundary (C). Read `bar_timestamp` to confirm it's a real recent session.
2. **Conviction/analogs/trade-plans/watchlists empty** is the deterministic consequence of the
   `if not stale:` gate (`actions.py:326`) — proven code path.
3. **The scan page mixes funnel stages by design**: 157 = universe, 30 = bars returned,
   6 = passed/persisted/displayed. The "Rows" field that should match the table is **6**, not
   30; the 30 is the *scanned/symbols* metric. No rows vanish between API and table.
4. **One real diagnostic gap flagged**: the `scanned → passed` drop has **no persisted
   per-symbol reason** — failed symbols are discarded, so the funnel's largest drop isn't
   auditable from the DB.
