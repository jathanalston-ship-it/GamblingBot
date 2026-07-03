# Autopilot

The fully hands-off loop: while the app is open, the market daemon scans,
**takes** the strongest committee-approved entries automatically, and manages
every position to its stops and targets. **OFF by default** — turning it on
is an explicit, persisted Settings decision. Paper money only; no live
brokerage is ever touched.

## What a day looks like with Autopilot ON

1. **04:00 ET (premarket)** — the daemon leaves its overnight 15-minute idle
   checks and scans every 60 seconds: live bars → momentum scan → conviction
   → trade plans → watchlists. Open positions are managed on every cycle.
   Entries **wait for the open** unless `include_premarket` is enabled.
2. **09:30–16:00 ET (regular)** — each cycle's final step
   (`api/autopilot_service.run_for_scan`, wired into `run_scan` *after*
   management so freed slots and heat are already known) ranks the cycle's
   conviction scores, keeps those at or above `min_conviction_score`
   (default 70 ≈ the HIGH band), and routes up to `max_entries_per_cycle`
   new symbols through **the exact same path as the "Take paper trade"
   button** — earnings gate, Investment Committee review (a decisive EXIT
   blocks the entry), plan-derived sizing, journal entry, tracking, linking.
   Management uses 1-minute prices in this window.
3. **16:00–20:00 ET (after-hours)** — scanning + management continue;
   no new entries.
4. Every auto-entry raises a deduped `autopilot_entry` **alert** (severity
   warning → clears the default OS-notification floor) and an activity row;
   the scan summary reports `autopilot_entries` + per-symbol outcomes
   (including every refusal's reason).

## Restraint (all persisted in `settings.yaml` under `autopilot:`)

| Knob | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | the master switch |
| `max_open_positions` | 8 | hard cap across the whole book |
| `max_entries_per_cycle` | 2 | restraint per 60-second cycle |
| `min_conviction_score` | 70 | selectivity floor (0–100) |
| `include_premarket` | `false` | premarket cycles scan & manage; entries wait for 09:30 |

Idempotent by construction: held symbols are never re-entered, and the
committee/earnings/plan gates run per take exactly as they do manually.

## Account balance

Settings → **Account & Autopilot → starting balance** persists to
`settings.yaml` (`account.starting_balance`, default $100,000) and is used
by paper sessions (`POST /actions/paper-session` when no explicit
`starting_equity` is passed) and by **new** brokerage accounts
(`brokerage_service.build_brokerage` seeds `starting_cash`). An account that
has already traded keeps its history — the balance only re-seeds the
brokerage account while it has zero fills.

## API

`GET/PUT /settings/autopilot` — enabled, caps, conviction floor, premarket
opt-in and `starting_balance` in one payload (partial updates).

## Requirements & honest limits

- The app must stay **open** — the daemon lives in the desktop process
  (laptop asleep = no scanning, no entries, no management).
- Entry prices are the scan's freshest price (daily bar / intraday print),
  filled on the paper journal — not a live order book.
- Premarket scans run on the freshest daily bars, so the meaningful entry
  and management action concentrates in regular hours.

## Tests

`tests/unit/api/test_autopilot.py`: off-by-default takes nothing;
enabled takes committee-reviewed entries with stops + alerts + persisted
meetings; per-cycle cap; premarket wait + opt-in; idempotent re-runs
(held symbols never duplicated); balance/settings round-trips.
