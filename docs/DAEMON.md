# Market Daemon — continuous market intelligence

Momentum Lab runs a **continuously running market-intelligence loop** for as
long as the application is open. No user interaction is required: the desktop
shell starts the backend with `MRP_DAEMON_AUTOSTART=1`, the daemon starts with
the app and stops with it.

## Architecture

```
desktop shell (Electron)
  └─ backend (FastAPI)  ── owns ──  MarketDaemon (dedicated daemon thread)
        │                              │ per tick:
        │  /daemon/* control+status    │  determine market state
        │  /timeline /deltas /alerts   │  → (scanning window) run one cycle
        │  /activity /scan-stats       │  → publish event → sleep interval
        │                              │
        └── the cycle = actions.run_scan through a CachingProvider:
            pull fresh data → scan universe → recompute conviction →
            update trade health (thesis reevaluation) → update watchlists →
            snapshot + deltas + alerts + activity + stats
            (command center / portfolio / thesis journal derive from these)
```

- `src/momentum/daemon/market_state.py` — **pure** US/Eastern schedule:
  premarket 04:00–09:30, regular 09:30–16:00, after hours 16:00–20:00
  (weekends/holidays via the shared `TradingCalendar`). Scanning windows tick
  every 60 s; outside them the daemon only wakes every 15 min to re-check the
  state — it **never scans while closed**.
- `src/momentum/daemon/worker.py` — the background worker (`MarketDaemon`),
  a dedicated daemon thread that never blocks the API/UI. `threading.Event`
  based sleeping means pause / resume / manual scan / shutdown interrupt any
  sleep instantly. **Error recovery**: a cycle failure (e.g. a temporary Yahoo
  outage) is recorded + published, and retried with capped exponential
  backoff — the loop never dies.
- `src/momentum/daemon/incremental.py` — **incremental reanalysis** (below).
- `src/momentum/api/daemon_service.py` — builds the injected cycle
  (settings-driven provider + selected universe → `run_scan`).
- Config: `config/daemon.example.yaml` (`DaemonConfig`, immutable Pydantic).

## Incremental reanalysis — don't rebuild the world every minute

- Every symbol's bars are **fingerprinted** (newest bar timestamp + last
  close). A pre-pass refreshes the universe through the shared
  `IncrementalCache`; when **no symbol changed** (and no manual scan was
  requested) the entire pipeline is **skipped** — prior conviction, analogs,
  trade-management state and watchlists remain valid untouched, which is
  identical to a full recompute by construction.
- `CachingProvider` wraps the real provider: bars pulled within
  `bar_reuse_seconds` are served from memory (**cache hits — zero API
  calls**); a close move beyond `price_change_threshold` always counts as
  changed. Because the wrapper implements the normal provider interface, the
  full pipeline runs unchanged on top of it — an incremental scan and a full
  scan persist identically.
- Metrics per cycle: `symbols_skipped`, `symbols_recomputed`,
  `cache_hit_rate`, duration — persisted on `scan_stats` and shown on the
  Command Center.

## Conviction delta engine + scan timeline

Every completed (non-stale) scan freezes an **immutable snapshot**
(`scan_snapshots`, migration `0025`) of candidates + conviction + trade
health + watchlists + trade state + regime + sector scores. The new snapshot
is diffed against the previous one (`timeline/diffing.py`, pure):
conviction / health / volume / relative-strength / ATR / momentum / price /
watchlist ranks / regime / sector / options — each changed metric becomes one
append-only `scan_deltas` row with previous value, new value, delta,
**UPGRADE / DOWNGRADE** direction, timestamp and reason (unchanged metrics
are not re-stated — they're derivable). History is never overwritten.

- `GET /timeline` · `GET /timeline/{id}` (replay) · `GET /timeline/diff?a=&b=`
  (diff any two snapshots)
- `GET /deltas?symbol=&metric=&direction=&since_hours=` (historical deltas)

## Live alert engine

After each diff, `timeline/alert_rules.py` (pure) turns important changes into
alerts: conviction |Δ| ≥ 5 (≥ 15 critical), trade health |Δ| ≥ 10 (≥ 25
critical), watchlist Top-5 entries (info) and removals (warning), stop reached
(critical) / target reached (warning) from tracked-trade state, regime changes
(critical), sector-leadership changes (warning), options-recommendation
changes (info). Each alert carries time / symbol / severity / title /
description and a **`dedupe_key` encoding the exact transition (unique
column)** — the same alert is never emitted twice. History: `GET /alerts`.

## Market activity feed

Every meaningful change (conviction moves, watchlist entries/exits/moves,
health changes, regime flips, options changes) becomes an `activities` row —
"NVDA conviction 91.00 → 96.00", "PLTR entered weekly watchlist at #2".
Newest first, filterable by category/symbol, cursor paging, persisted forever
(append-only). `GET /activity`.

## Scan performance tracking

Every scan appends a `scan_stats` row: duration, symbols processed/failed,
provider latency, database writes, convictions/watchlists/alerts/deltas/
activities generated, incremental metrics, process memory (peak RSS) and CPU.
A scan slower than 2× its recent median raises a `performance` alert.
`GET /scan-stats` + `GET /scan-stats/summary`; dashboard panel on the Command
Center.

## API summary

| Route | Purpose |
| --- | --- |
| `GET /daemon/status` | worker status (state, schedule, last/next scan, failures, version); 200 with `running:false` when disabled |
| `GET /daemon/events` | recent published daemon events |
| `POST /daemon/pause` / `resume` | pause/resume scheduled scanning |
| `POST /daemon/scan-now` | manual scan / immediate refresh (interrupts any sleep) |

## Desktop integration

- The Electron shell sets `MRP_DAEMON_AUTOSTART=1` (opt out by exporting `0`;
  CI smoke mode disables it automatically).
- **Command Center** now opens with the live pulse: daemon strip (status dot,
  market state, last scan, a ticking next-scan countdown, cycle count,
  pause/resume + scan-now buttons), top gainers/losers, largest conviction and
  health changes, watchlist movers, recent alerts, the activity feed and the
  scan-performance panel — all polling (3–10 s), no manual refresh ever needed.
- **Live difference visualization** (`DeltaValue`): every changed value shows
  the previous value struck through beside the new one, a direction arrow, and
  a green (up) / red (down) / orange (caution) flash — changes are never hidden.
- **Timeline view**: the snapshot list; click one to replay it, two to diff.

## Testing

`tests/unit/daemon/` (schedule incl. holidays, worker controls + error
recovery + backoff, incremental cache/provider), `tests/unit/timeline/`
(diff directions/epsilon/appear-disappear, alert thresholds + dedupe keys +
activity phrasing), `tests/unit/api/test_market_pulse.py` (two live-shaped
scans → snapshots/deltas/alerts/activities/stats; alert dedup on rescan;
immutability; all routes; daemon cycle skip-when-unchanged with cache-hit
metrics). All offline (stub provider, in-memory SQLite, tiny sleeps).
