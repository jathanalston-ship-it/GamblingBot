# Universe Management

The scanner can target **multiple universes** — built-in index sets and
user-defined lists — instead of one hardcoded symbol set. You pick a universe in
**Settings → Scanner Universe**; the selection is persisted and every **Run Scan**
processes exactly that universe, reporting its size, how many symbols were
scanned, how many passed the gate, and how long it took.

## Universes

### Built-in (shipped, config-overridable)

| Key | Label | Notes |
|---|---|---|
| `default` | Default (Large-Cap) | The platform's curated large-cap set (`universe/membership.py`). |
| `sp500` | S&P 500 | Large-cap S&P 500 seed. |
| `nasdaq100` | NASDAQ 100 | The 100 largest non-financial Nasdaq names. |
| `russell1000` | Russell 1000 | Broad large/mid-cap **extendable seed**. |
| `russell3000` | Russell 3000 | Broad market **extendable seed**. |
| `all` | All Tradable Stocks | Every tradable US equity **extendable seed**. |

Built-in member lists live in `config/universes.example.yaml` (embedded default in
`universe/universes.py`, so a packaged build needs no repo file; user override at
`<MRP_USER_DIR>/config/universes.yaml`). The broad sets (`russell1000/3000`,
`all`) **ship as seeds**: the engine processes a universe of any size (verified to
3000+ — see Verification), and the full membership is loaded by **importing** a
list from your own data source. The size shown everywhere is the *actual* loaded
count, never a fabricated number.

### User universes (persisted in `user_universes`)

- **Custom watchlist** — a hand-entered symbol list.
- **Imported symbol list** — a pasted/comma/newline-separated list, parsed and
  validated (tickers only; notes/headers dropped).
- **Sector universe** — a base universe filtered to one GICS sector
  (`Energy`, `Information Technology`, …).

## Architecture

```
Settings ─▶ GET/PUT /universes[...]        ─▶ universe_service ─▶ UserUniverseRepository
                                                   │                    (user_universes table)
                                                   ├─ builtin registry (universe/universes.py)
                                                   └─ selection (settings.yaml: universe.selected)

Run Scan ─▶ POST /actions/scan ─▶ _selected_universe(request)
                                     │  explicit body symbols, else resolve_selected()
                                     ▼
                                  actions.run_scan(symbols, sectors, universe_key, universe_label)
                                     ▼  reports: universe_size · symbols_scanned · symbols_passed · duration_ms
```

- **Registry** (`src/momentum/universe/universes.py`) — built-in defs + member
  lists, `parse_symbols`, sector map, `resolve_builtin`. Pure, no I/O beyond
  config load.
- **Service** (`src/momentum/api/universe_service.py`) — list/resolve/create/
  import/sector/select/delete; bridges the registry and the DB; resolves the
  selected universe for the scan.
- **Persistence** — `UserUniverse` model + `user_universes` table (migration
  `0015`); symbol list stored as JSON (a universe can hold thousands of symbols).
  The selected key persists to `settings.yaml` (`universe.selected`) via
  `user_settings.read/write_selected_universe`.
- **Routes** (`src/momentum/api/routes/universes.py`) — `GET /universes`,
  `GET/PUT /universes/selected`, `POST /universes`, `POST /universes/import`,
  `POST /universes/sector`, `DELETE /universes/{key}`.
- **Scan wiring** (`src/momentum/api/routes/actions.py`) — `_selected_universe`
  resolves the chosen universe (or an explicit request body); `run_scan` measures
  and returns the four display stats.
- **Frontend** — Settings **Scanner Universe** panel (selector with sizes +
  create/import/sector + delete) and a **Scanner** stats strip (universe / size /
  scanned / passed / duration), plus a compact summary on the Run-scan button.

## Scale & freshness (large universes)

- **Liquidity prefilter + cap** (`universe/prefilter.py`) — before the full scan,
  `run_scan` applies a cheap pre-pass (last-price floor + recent dollar volume,
  reusing the scanner's own floors) and keeps the most-liquid **`max_symbols`**.
  So "All Tradable Stocks" (5000+) stays responsive: it pulls everything but fully
  scans only the top-N by liquidity. Cap via `max_symbols` (param) →
  `MRP_MAX_SCAN_SYMBOLS` (env) → `2000` default; `0` disables it. The scan result
  reports both `symbols_pulled` and `symbols_scanned`.

- **Hybrid refresh** (`POST /universes/{key}/refresh`) — the shipped seed lists are
  the source of truth, but a built-in universe can be **refreshed live** when the
  active data provider can enumerate constituents (a `list_symbols` capability —
  Alpaca/Polygon-style). yfinance can't, so its universes keep the seed (the
  endpoint returns 400 "does not support…"). A successful refresh writes a user
  override to `<MRP_USER_DIR>/config/universes.yaml`, so it takes effect
  immediately and survives restarts. The Settings panel shows a **Refresh** button
  on each built-in (non-`default`) universe.

## API

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/universes` | — | List built-in + user universes (with sizes), the selection, and known sectors. |
| GET | `/universes/selected` | — | The resolved selected universe (key, label, size, sample symbols). |
| PUT | `/universes/selected` | `{key}` | Persist the selection (400 if unknown). |
| POST | `/universes` | `{label, symbols[]}` | Create a custom universe (201). |
| POST | `/universes/import` | `{label, text}` | Parse + create an imported universe (201). |
| POST | `/universes/sector` | `{sector, base?}` | Create a sector universe (201). |
| POST | `/universes/{key}/refresh` | — | Refresh a built-in from the provider (400 if unsupported / not refreshable). |
| DELETE | `/universes/{key}` | — | Delete a user universe (400 for built-ins, 404 if absent). |

## Verification

Automated (all in the suite):

- **Registry** (`tests/unit/universe/test_universes.py`) — required built-ins
  present, sizes, sector map, messy-list parsing, and a **drift guard** that the
  shipped YAML equals the embedded default.
- **Service** (`tests/unit/api/test_universe_service.py`) — list/select/resolve,
  create/import/sector round-trips, delete-resets-selection, and the built-in /
  empty-list guards.
- **REST + scan wiring** (`tests/unit/api/test_universes_api.py`) — the full
  endpoint surface, and **selecting a universe makes Run Scan process exactly that
  set** (asserting `universe_size` / `symbols_scanned` / `symbols_passed` /
  `duration_ms`).
- **Scale** — the scanner processes **500** and **1000** symbol universes
  (parametrized), a **3000**-symbol universe (`@pytest.mark.slow`), and
  `run_scan` persists scan + conviction over a **600**-symbol universe. This is
  the 500+/1000+/3000+ requirement, proven on synthetic universes so it runs
  offline and fast.

Manual (desktop):

1. **Settings → Scanner Universe** — select **NASDAQ 100** (size 100). 
2. **Scanner → Run scan** — the stats strip shows universe **NASDAQ 100**, size
   **100**, the scanned/passed counts and the duration.
3. Create a **Custom** or **Imported** universe, select it, scan again — the scan
   processes your list.

## Files

- `src/momentum/universe/universes.py` — registry + built-in lists + parsing.
- `config/universes.example.yaml` — shipped built-in member lists.
- `src/momentum/persistence/models/user_universe.py` + migration `0015` +
  `repositories/user_universes.py` — persistence.
- `src/momentum/api/universe_service.py`, `routes/universes.py` — service + REST.
- `src/momentum/api/{actions.py,routes/actions.py}` — selected-universe scan + stats.
- `src/momentum/api/user_settings.py` — selection persistence.
- `desktop/renderer/src/views/{Settings,Scan}.tsx`, `components/ActionButton.tsx`,
  `api/types.ts` — frontend.
