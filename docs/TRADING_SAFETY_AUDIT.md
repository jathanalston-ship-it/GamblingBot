# Trading Safety Audit — 2026-07-03

Premise: pretend the application controls **$250,000**. Every hazard on the
checklist was attacked with an executed test — stress (seeded randomness at
volume), soak (thousands of iterations with bounded-memory assertions) and
concurrency (real threads on a file-backed SQLite engine, the desktop
deployment's actual database). Suites:
`tests/unit/audit/test_trading_safety.py` (16 tests) and
`tests/unit/api/test_trading_mutex.py` (5 tests). Everything discovered was
fixed in this audit; the full suite (1617 tests) is green.

## Verdict per hazard

| Hazard | Result | Evidence |
| --- | --- | --- |
| Duplicate orders | **SAFE (fixed)** | Sequential replay of a `client_order_id` returns the original order (1 row). 8 threads racing the same id keep exactly one row — the unique index + new `IntegrityError` absorption in `place_order` |
| Duplicate scans | **SAFE (fixed)** | Same-day re-scans replace per `run_id` (no row growth, readiness suite); *concurrent* scans are now **refused** by the trading mutex |
| Duplicate trade management | **SAFE** | Repeat scans on identical gapped data sequence one action per cycle (by design), never repeat one: quantity only falls, stops only tighten, closes stay closed, and the book reaches a **fixed point** |
| Race conditions | **SAFE (fixed)** | New process-wide trading mutex (`api/trading_mutex.py`): scan, paper-session, seed-demo, reevaluate, watchlists/lifecycles and the synchronous Take/Track/Close actions are serialized; a second thread is refused immediately (HTTP 409 at the routes), re-entrant on the same thread so autopilot-inside-scan cannot deadlock |
| Stale data decisions | **SAFE** | A scan on month-old bars is flagged stale, generates **zero** conviction and autopilot takes **nothing** |
| Missing stop losses | **SAFE** | Every automated entry carries `initial_stop > 0` strictly below entry; stop-breach management closes with a persisted, data-only reason |
| Invalid sizing | **SAFE** | Entries flow from plan-derived risk sizing; a zero/absent size refuses the take; venue positions can never go negative (300-op stress) |
| Negative buying power | **SAFE (fixed)** | Placement checks settled-cash buying power; execution re-checks at the real quote. A working order that becomes unaffordable used to **crash the venue tick** (illegal `working → rejected` transition) — it is now **cancelled loudly** with the reason persisted; cash untouched; `buying_power >= 0` held across the stress run |
| Impossible fills | **SAFE** | 400 seeded executions (realistic + pessimistic): a buy never fills below the ask, a sell never above the bid, limits are never violated, quantity never exceeds the request, prices/fees never negative; overfills raise in the OMS |
| Infinite loops | **SAFE** | Missed-scan gap math is capped (10-year gap computes in <5s); failure backoff is capped at `backoff_max_seconds`; every scheduler delay is strictly positive (no busy loop) |
| Memory leaks | **SAFE** | Soak: 20k events + 2k cycles — the event buffer stays at its cap and the steady-state half allocates <1MB (tracemalloc); `JobManager` history is bounded (50) |
| Scheduler drift | **SAFE (documented)** | Delays are positive and bounded for every state × failure count. The loop sleeps a fixed interval *after* each cycle, so the effective period is `cycle_duration + interval` — bounded per-tick, anchored to the real clock each iteration, never cumulative |
| Orphaned workers | **SAFE** | 5× start/stop joins the daemon thread every time (`active_count` returns to baseline); job threads are daemon threads (die with the process); Electron kills the backend on quit |

## Issues found and fixed

| # | Issue | Severity | Likelihood | Fix | Verification |
| --- | --- | --- | --- | --- | --- |
| 1 | **No mutual exclusion between trading pipelines.** The daemon cycle, the manual Run-Scan job, manual reevaluation and the Take/Track/Close actions could run concurrently — two writers interleaving `replace_for` on one `run_id`, double-entering a symbol past the check-then-insert held guard, or double-firing a scale-out past the read-then-write target flag | **High** (money double-managed) | Medium (one click during any daemon cycle) | `api/trading_mutex.py`: process-wide re-entrant mutex, refuse-don't-queue; wired into every mutating pipeline (`@serialized`) and the synchronous trade routes (409 on busy) | `test_concurrent_scans_are_refused_not_interleaved`, `test_manual_trade_actions_are_refused_mid_scan`, `test_trading_mutex.py` (5 semantics tests) |
| 2 | **Venue tick crash on unaffordable working orders.** `PaperBrokerage._execute` rejected a WORKING order at execution-time affordability failure — an illegal state transition that raised and aborted the whole `process_tick` (every other order that tick unprocessed) | **High** (venue stops filling) | Medium (any accepted order the account can no longer afford) | Cancel (legal, terminal, loud) instead of reject; reason persisted on the order's event trail | `test_order_beyond_buying_power_rejected_and_cash_untouched` |
| 3 | **Duplicate-order race window.** `place_order`'s idempotency was check-then-insert; two threads racing the same `client_order_id` made one of them crash with a raw `IntegrityError` | Medium | Low (needs concurrent submission) | Absorb the `IntegrityError`: roll back and return the winner's order — idempotent under race | `test_concurrent_duplicate_orders_keep_exactly_one` (8-thread barrier race) |

## Observations (verified safe, no change needed)

- **One action per cycle** is deliberate: a 35% gap sequences scale-out →
  next target → breakeven raise across cycles rather than firing everything
  in one tick; the audit proves the sequence converges and never repeats.
- **Closed-then-re-eligible**: after a final-target close, a symbol can be
  re-entered by autopilot on a later cycle if it still ranks — gated by
  conviction floor, committee review and the per-cycle/book caps.
- **Append-only guarantees** already covered elsewhere: order events,
  account history, evaluations and audit log all refuse deletes.

## How to re-run

```bash
PYTHONPATH=src python -m pytest tests/unit/audit/test_trading_safety.py \
    tests/unit/api/test_trading_mutex.py -q
```
