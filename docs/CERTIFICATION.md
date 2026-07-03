# Paper Trading Certification

The gate before live trading is even a conversation: Momentum Lab must prove
**30 consecutive calendar days** of continuous, boring, uneventful paper
operation. The report never certifies until every requirement passes.

## How it works

A pure engine (`src/momentum/certification/`) grades the last
`window_days` (default 30) from surfaces that already exist — no new
tables, always recomputable:

| Source | Feeds |
| --- | --- |
| `scan_stats` | scan coverage/uptime, missed scans, scheduler drift, per-scan RSS (memory growth), p95 duration |
| `runs` | API failures (jobs that errored) |
| `trades` | opened / closed / duplicate detection |
| `alerts` | alert volume, warning/critical counts |
| `market_data_provenance` | provider (Yahoo) failures |
| `automation_state.json` | crash history (every recovery is appended, capped 50) |
| live `PRAGMA integrity_check` | database corruption |
| `MRP_PARENT_PID` | orphan protection (the parent watchdog) |

**Coverage model** (`engine._walk_days`): every minute the ET schedule says
the daemon should be scanning is checked for a scan within tolerance
(180s). Per ET calendar day this yields uncovered minutes and the largest
gap; a crash recovery marks its day bad. The **streak** is the run of
consecutive clean calendar days ending today — clean weekends/holidays
extend it (the spec counts calendar days), any missed scanning minute or
crash resets it to zero and certification rebuilds.

## Requirements (all must pass)

| Requirement | Measured | Kind |
| --- | --- | --- |
| No crashes | crash recoveries in the streak | streak-scoped (a crash resets the streak) |
| No orphaned backend | parent watchdog active | stateful |
| No scheduler drift | largest in-session gap ≤ 300s | streak-scoped |
| No missed scans | 0 uncovered scanning minutes | streak-scoped |
| No duplicate trades | >1 open per symbol, or identical (symbol, entry) rows | stateful |
| No database corruption | live `integrity_check == ok` | stateful |
| Memory bounded | last-decile vs first-decile median RSS ≤ 300MB | stateful |
| No UI freezes (proxy) | p95 scan duration ≤ 120s — renderer freezes are not backend-observable; the honest proxy is the pipeline latency the UI blocks on | stateful |
| 30 consecutive days | streak ≥ `window_days` | the calendar |

**Status semantics**: `certified` (everything passed over the full window),
`failing` (something is wrong *right now* — corruption, duplicates, no
watchdog, memory, latency), `in_progress` (operation is clean but the
streak hasn't reached 30 days yet; a crash yesterday means "day 1 of 30",
not a permanent black mark).

## Tracked metrics

Uptime (scan coverage %), scans completed, trades opened/closed, alerts
generated, errors (failed runs + critical alerts), warnings
(warning alerts + degraded scans), API failures (failed runs), provider
failures (provenance rows with an error).

## API + UI

`GET /certification` — the full report (status, day N of 30, metrics,
every requirement with measured/threshold/detail). Desktop:
**System → Certification** (status badge, day progress bar, metric grid,
requirement checklist).

## Tests

`tests/unit/certification/test_engine.py` (8): full clean window certifies,
partial window is in-progress, a crash resets the streak, missed scans
break their day, stateful problems fail outright, memory growth fails,
day-zero fresh install, clean weekends extend the calendar streak.
`tests/unit/api/test_certification.py` (5): metric tracking against real
rows, crash history via `automation_state`, duplicate open trades fail,
bare CLI sessions cannot certify, endpoint round-trip.
