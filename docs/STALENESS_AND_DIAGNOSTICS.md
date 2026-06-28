# Trading-session freshness + scan diagnostics

Three fixes that together stop a healthy scan from looking broken and make the
funnel's drops explainable.

## 1. Trading-session-aware staleness (the real fix)

**Problem.** A scan was flagged `stale` when its newest bar was older than a
**4-day wall-clock** threshold. With daily yfinance bars the newest bar is
routinely 3–5 *calendar* days old over a weekend/holiday (or before today's
session bar exists), so a perfectly fresh scan was flagged stale and the
`if not stale:` gate skipped **conviction → trade plans → analogs → watchlists**
for the whole run. Every downstream screen went empty while the scan table stayed
populated — the classic "looks broken" symptom.

**Fix.** Freshness is now measured in **trading sessions**, not wall-clock time
(`actions._evaluate_staleness` / `_sessions_behind`, using
`data.calendar.TradingCalendar`). A Friday bar read on Monday is **0–1 sessions
behind → fresh**. A scan is stale only when the newest bar is more than
`DEFAULT_MAX_STALE_SESSIONS` (**2**, override `MRP_MAX_STALE_SESSIONS`) completed
sessions behind the latest session as of the pull. Weekends and exchange holidays
are skipped by the calendar.

`data_age_minutes` (wall-clock) is still reported for display. The legacy
wall-clock-minutes rule is preserved for **intraday** callers: pass
`stale_after_minutes=` or set `MRP_STALE_AFTER_MINUTES` to opt back into it.

`run_scan` now also returns `stale_reason` and `sessions_behind`. The desktop
surfaces a prominent **Stale Data** banner (a shared `StaleBanner` component) on
the **Conviction** and **Watchlists** screens — not just the Scanner — so a stale
run explains the empty screens instead of mystifying.

## 2. Persisted failure reasons (diagnostics)

Previously neither failure reason was recoverable from the DB.

- **Fetch failures** — `market_data_provenance` gained an `error` column
  (migration `0020`). `pull_bars` now records *why* a fetch returned no bars:
  the exception text, or `"provider returned no rows"` for an empty response
  (NULL on success). The scan / refresh / verify paths all populate it.
- **Scanner-gate drops** — a new `scan_rejections` table (migration `0021`) stores
  **one row per scanned-but-rejected symbol** with the name of the **first** filter
  that eliminated it (`combine` now records a per-symbol `reasons` map alongside the
  aggregate counts). This explains the scanned→passed drop that `scan_results`
  (passed-only) hides. Idempotent per `(run_id, symbol)`; read via
  `GET /universe/rejections`. NB: penny/illiquid names are removed by the liquidity
  *prefilter* before the scan, so they appear in neither table.

## 3. Conviction list cap

`GET /conviction` defaulted to `limit=100`, silently truncating a run with >100
candidates. The default is now `2000` (the max). Latent today (the Conviction view
queries per-symbol), but correct for any bulk consumer.

## Tests

`tests/unit/api/test_staleness.py` (session math, weekend/holiday skip, minute
override), `tests/unit/api/test_scan_rejections.py` (rejection persistence + reason,
fetch-error reason, endpoint, idempotent re-run), and an extended
`tests/unit/universe/test_filters.py` (per-symbol `reasons`).
