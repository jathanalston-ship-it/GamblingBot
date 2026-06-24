# Live Scan Pipeline Audit (read-only — no fixes)

**Symptom:** the scanner runs against a live universe (96 symbols), but Scan results
stay identical to demo data and Watchlists say *"No live conviction data available."*

**Method:** the real pipeline was run offline end-to-end (`scratchpad/audit_pipeline.py`
+ `audit_scenarios.py`): seed demo → `run_scan` with a stub provider → inspect every
DB table and every read endpoint. Three scenarios by newest-bar date.

## Reproduced result (the smoking gun)

| Scenario (newest bar) | live conviction persisted | `GET /scan` top rows | Watchlist source |
|---|---|---|---|
| **A — today** | 48 (run `scan-YYYYMMDD`) | **demo + live interleaved** | mixed demo + live |
| **B — yesterday** (normal daily case) | 48 persisted | **all demo** | **demo (15 cands)** |
| **C — 5 days old** (stale) | 0 (skipped) | all demo | demo |

In **B and C — the everyday cases — the live scan persists correctly but never
surfaces.** Persistence is not the problem; **selection on read is.**

## Per-stage trace

| Stage | Input source | Output object | Table written | run_id | Timestamp | Persists? | UI reads same run_id? | Broken? | Root cause |
|---|---|---|---|---|---|---|---|---|---|
| Settings | `settings.yaml` | provider/universe choice | — | — | — | n/a | n/a | ✅ | — |
| Data Provider | `user_settings.build_provider` | `MarketDataProvider` | — | — | — | n/a | n/a | ✅ | — |
| Universe | `resolve_selected` / `select_universe` | `(symbols, sectors)` (96) | — | — | — | n/a | n/a | ✅ | — |
| Scanner | live bars | `ScanResult.candidates` | — | `scan-<barDate>` | `scan.as_of` = **newest bar date** | n/a | n/a | ✅ | — |
| Candidate Gen | scan features | `ScanCandidate[]` | — | same | same | n/a | n/a | ✅ | — |
| Conviction | candidates + regime | `ConvictionScore[]` | — | same | `ts=now` | n/a | n/a | ⚠️ | **skipped entirely when data is stale** (by design) |
| **Persistence** | the above | rows | `scan_results`, `conviction_scores`, `market_regimes`, `scan_metadata`, `runs` | **all = `scan-<barDate>`** ✅ | consistent | **✅ yes** | — | ✅ | persistence is correct & atomic |
| **API (read)** | DB | `ScanResultOut` / `ConvictionScoreOut` / watchlists | — | **none — selects “latest by `as_of` across ALL run_ids”** | `as_of DESC` | n/a | **❌ NO** | **❌ BROKEN** | reads blend runs and rank by date; **demo is dated *today*, live is dated the *newest bar* (≈ yesterday)** → demo always wins |
| UI | API JSON | tables | — | — | — | n/a | ❌ | ❌ | faithfully shows whatever the API returns (= demo) |

## First point where live data is lost

**The API read/selection layer — not persistence.** Concretely:

- `services.list_scans(run_id=None)` → `ORDER BY as_of DESC, rank ASC` across **all**
  run_ids (no run scoping). `GET /scan` therefore interleaves or is dominated by demo.
- `services.list_conviction(run_id=None)` → `ORDER BY as_of DESC` across all run_ids.
- `watchlist_service._winning_batch` → `as_of = max(as_of)` **first**, only then prefers
  live *at that date*. The live tie-break never triggers because demo's `as_of` is a
  strictly newer date.
- `get_watchlists(run_id=None)` → `latest_date(None)` + `for_date(date, run_id=None)` →
  newest date across all runs, then every entry at that date (demo + live mixed).

### The underlying cause
Two design choices collide:
1. **Demo is dated `today`** (`demo.seed_all`: `as_of = _bdays(today,120)[-1]`).
2. **A live scan is dated the newest *bar* date** (`run_id = scan-<bar date>`,
   `as_of = scan.as_of.date()`). For daily market data the freshest completed bar is
   normally **yesterday**, so the live run's `as_of` < demo's `as_of`.

Because every "latest" read selects purely by `as_of`, **demo's today-dated rows
outrank the live scan's yesterday-dated rows in every screen.** In **production mode**
(demo purged) the same reads instead find no live conviction when the scan was stale,
producing *"No live conviction data available."*

### Contributing (secondary) issues
- **Reads are not run-scoped:** they blend multiple `run_id`s instead of pinning the one
  authoritative run.
- **Run Scan does not (re)generate watchlists** — that is a separate action, so even a
  correct live conviction batch isn't reflected on the Watchlists screen until the user
  clicks Generate.
- **Stale gate** skips conviction (correct), but with demo present this silently leaves
  the screens on demo.

## Conclusion
Persistence already writes `scan_results`, `conviction_scores`, `market_regimes`,
`scan_metadata` and `runs` under one consistent `run_id`. **The fix belongs entirely on
the read/selection side:** every "latest" read must resolve to the latest **live** run and
never rank demo above live by date. (Implemented in the follow-up task.)
