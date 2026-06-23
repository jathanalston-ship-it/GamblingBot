# Scan Pipeline Verification

A scan used to be able to "succeed" without any proof that **fresh** market data
was actually pulled. Now every scan records its provenance and freshness, and a
**stale** scan is blocked from generating conviction.

## What every scan now does

1. **Build the provider from Settings** — the scan action constructs the
   configured market-data provider (`user_settings.build_provider`) and passes its
   name (`yfinance` / `alpaca` / `polygon`) into `run_scan`.
2. **Connect + pull fresh bars** — `pull_bars` calls the provider for the selected
   universe; if nothing comes back the scan **fails loudly** (`"no market data
   returned by provider … (connection/auth failure or empty response)"`) rather
   than silently producing an empty result.
3. **Verify the newest bar timestamp** — `run_scan` computes the most recent bar
   timestamp across all pulled frames and the **data age** = `pull_time −
   newest_bar` (minutes).
4. **Store scan metadata** — a row in **`scan_metadata`** (migration `0016`),
   idempotent per `scan_id`.
5. **Gate conviction on freshness** — if `data_age_minutes` exceeds the threshold
   the scan is flagged **stale** and **conviction is not generated** (so a stale
   scan can never feed the watchlists / conviction screens). Scan results + regime
   + metadata are still persisted, with `stale=true`.

### `scan_metadata` fields

| Field | Meaning |
|---|---|
| `scan_id` | the scan run id (`scan-YYYYMMDD`) |
| `provider` | provider used (`yfinance` / …) |
| `universe` | the universe label/key scanned |
| `bar_timestamp` | newest bar pulled (UTC) |
| `pull_timestamp` | when the pull happened (UTC) |
| `symbol_count` | symbols that returned data |
| `data_age_minutes` | `pull_timestamp − bar_timestamp` |
| `stale` | whether the scan exceeded the freshness threshold |

### Freshness threshold

`stale_after_minutes` (parameter) → `MRP_STALE_AFTER_MINUTES` (env) →
`DEFAULT_STALE_AFTER_MINUTES` (4 days). The default tolerates weekends/holidays
for **daily** bars while still catching a provider that returns week-old data; the
desktop/intraday can set a tighter value. If the newest bar timestamp can't be
determined at all, the scan is treated as stale (freshness can't be proven).

## Display (Scanner header)

`GET /universe/scan-metadata` returns the latest scan's metadata (or `null`). The
Scanner header renders:

```
Provider: yfinance   Symbols: 1274   Data age: 3.2h   Last pull: 14:31:05
```

When the scan is stale the header turns red with a **STALE DATA** badge and
*"conviction not generated — data too old"*.

## Verification report

Automated (`tests/unit/api/test_scan_verification.py`):

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Fresh scan records metadata + generates conviction | ✅ | `test_fresh_scan_records_metadata_and_generates_conviction` — `stale=false`, metadata row (provider/universe/symbol_count/bar_timestamp), conviction == candidates. |
| 2 | Stale scan is flagged + **blocks** conviction | ✅ | `test_stale_scan_is_flagged_and_blocks_conviction` — 30-day-old feed, `stale=true`, `conviction_scores_persisted == 0`, scan results still saved. |
| 3 | Threshold is configurable | ✅ | `test_threshold_override_makes_old_data_acceptable` — a generous threshold makes the same old data acceptable + conviction generated. |
| 4 | Metadata is idempotent per scan | ✅ | `test_scan_metadata_is_idempotent_per_scan` — two runs ⇒ one row. |
| 5 | Header endpoint | ✅ | `test_scan_metadata_endpoint` — `null` before a scan; after, `symbol_count`/`stale`/`pull_timestamp`/`provider` populated. |
| 6 | Empty/failed pull fails loudly | ✅ | `run_scan` raises a provider-named `RuntimeError` (existing `test_run_scan_fails_with_no_data`). |
| 7 | No regression | ✅ | full suite green (existing scan tests updated to pull *fresh*-dated bars, reflecting a real pull). |

### The guarantee

> A scan cannot complete "successfully" while silently using stale data.

Freshness is computed from the actual pulled bars and persisted on every scan; a
scan past the threshold is marked `stale` and **does not produce conviction**, so
stale data can never propagate into the conviction/watchlist screens, and the
Scanner header always shows the provider, symbol count, data age and last-pull
time (with a STALE DATA warning when applicable).

## Files

- `src/momentum/persistence/models/scan_metadata.py` + migration `0016` +
  `repositories/scan_metadata.py` — persistence.
- `src/momentum/api/actions.py` — freshness check, conviction gate, metadata write
  (`run_scan`); `_newest_bar_timestamp`, `_stale_threshold`.
- `src/momentum/api/routes/universe.py` — `GET /universe/scan-metadata`.
- `src/momentum/api/routes/actions.py` — passes the provider name into the scan.
- `desktop/renderer/src/views/Scan.tsx` — the Scanner header + STALE DATA banner.
- `tests/unit/api/test_scan_verification.py` — verification tests.
