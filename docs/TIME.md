# Time handling — UTC storage, local display, market-aware scheduling

The platform's time policy in one line: **store UTC, schedule in
America/New_York, display in the user's OS timezone with the OS locale.**
The user never configures a timezone.

## Architecture

```
persistence (SQLite)      backend (FastAPI)              renderer (Electron)
  UTC instants        →     UTC / ET ISO strings     →     OS timezone + locale
  (offset dropped by         (offsets on everything          (Intl.DateTimeFormat,
   SQLite round-trip)         computed; market logic          parseUtc appends "Z"
                              in America/New_York)            to offset-less UTC)
```

### Backend — UTC everywhere, never local

- Every "now" is `datetime.now(tz=dt.UTC)`. **Enforced by test**:
  `tests/unit/core/test_time_audit.py` AST-scans the whole package and fails
  on any naive `datetime.now()` or deprecated `utcnow()`.
- Columns are `DateTime(timezone=True)` and receive aware-UTC values. SQLite
  round-trips them **naive** (`2026-07-01T19:30:00`, no offset) — the audit
  test pins the contract that this naive value *is* UTC, which is exactly what
  the frontend's `parseUtc` assumes. Local time is never stored.
- The backend never renders local time — it can't know the user's zone. It
  serves unambiguous values: UTC/ET ISO strings **with offsets** and countdown
  seconds (`GET /daemon/clock`).

### Market awareness — America/New_York, never hardcoded offsets

- All market logic (`daemon/market_state.py`) constructs instants **in**
  `ZoneInfo("America/New_York")`: 09:30 is 09:30 ET whether that day is EST or
  EDT, so daylight-saving transitions are exact by construction. The scheduler
  converts the UTC clock → market time internally; it never uses the local
  clock.
- "EST"/"EDT" appear only as *derived* display abbreviations (`strftime("%Z")`
  / Intl `timeZoneName`). **Enforced by test**: the audit gate fails on any
  hardcoded `"EST"`, `"EDT"`, `"US/Eastern"`, `"EST5EDT"` or fixed-offset zone
  literal in the package.
- `market_clock(now)` (pure, DST-tested) returns the market state, market time
  + tz abbreviation, and the next premarket/open/close instants + countdown
  seconds, holiday-aware via the shared `TradingCalendar`.

### Frontend — the only place local time exists

- `renderer/src/lib/format.ts` is the single rendering point:
  - `parseUtc(iso)` — offset-less backend strings are UTC; append `Z` before
    parsing (a bare `new Date(iso)` would parse them as *local* and silently
    shift every timestamp by the UTC offset — the bug this refactor removed).
  - `date` / `fmtTime` / `dateTime` — `Intl.DateTimeFormat(undefined, …)`:
    the OS timezone and the OS locale decide layout **and** 12/24-hour clocks
    (`8:43 AM` vs `20:43`; `Jun 22, 2026` vs `22 Jun 2026`).
  - Date-only values (trading-day `as_of`) render as calendar dates, never
    timezone-shifted across midnight.
  - `timeInZone(d, zone)` — explicit-zone rendering for the market clock
    ("09:32 EDT" beside "06:32 PDT").
- Every view already formats through these helpers, so Last/Next Scan, trades
  opened/closed, watchlists, evaluations, conviction, notifications, journal,
  replay, analytics, portfolio history, command center, updates, activity
  feed, logs and provenance all render local + locale automatically.
- **OS timezone changes, live**: `useSystemTimezone` polls
  `Intl.DateTimeFormat().resolvedOptions().timeZone` (5s); `AppShell` keys the
  routed view on it, so a change remounts the UI and every timestamp
  re-renders — no restart, no setting.

## Live Clock & Market Status widget

`components/LiveClock.tsx` (Command Center header — the landing dashboard):
current **local** time and **market** time (both with derived tz
abbreviations), the current IANA zone, the market status badge
(Closed / Premarket / Open / After Hours), and ticking countdowns — next scan
(from the daemon), market open, market close, next premarket. Ticks every
second; countdowns interpolate client-side between 30s polls of
`GET /daemon/clock`; follows OS timezone changes live.

## Tests

- `tests/unit/daemon/test_market_clock.py` — conversions, EST↔EDT, weekend +
  holiday skips, **both DST transitions** (spring-forward 2026-03-08 and
  fall-back 2026-11-01, including the elapsed-hours asymmetry), no-ambiguity
  (every emitted timestamp carries an offset), naive-input rejection.
- `tests/unit/core/test_time_audit.py` — the enforcement gate: no naive
  `now()`, no `utcnow()`, no hardcoded Eastern zone strings, and the UTC
  persistence round-trip contract.
- `desktop/scripts/local-time.test.cjs` — the renderer contract under a forced
  non-UTC process zone: offset-less ⇒ UTC parsing (and the shift the naive
  parse would have caused), locale-driven 12/24-hour + date layouts, market
  rendering in America/New_York across DST, OS-zone detectability, countdowns.
