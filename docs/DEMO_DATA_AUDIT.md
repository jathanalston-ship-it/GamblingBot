# Demo-Data Audit + Production Guards

Sweep of `demo / sample / seed / mock / fixture / fallback / example / hardcoded
tickers` across the codebase, each classified, plus the guards that make demo data
**impossible** to seed or surface in production.

## Classification

| file:line | what | classification | reason |
|---|---|---|---|
| `src/momentum/demo.py` (`seed_all`, `SYMBOLS`) | the demo dataset generator + its 15 demo tickers | **Onboarding** | first-run "Load sample data" so every screen shows realistic data; now **guarded** (raises in production) |
| `src/momentum/api/actions.py:549` `seed_demo_data` | operator-console seed action | **Onboarding** | "Load sample data" button; refuses in production (`is_production`) |
| `src/momentum/api/routes/actions.py` `/actions/seed-demo`, `/actions/reset` (load_demo) | HTTP seed entrypoints | **Onboarding** | both gate on `is_production` → 409 / refusal |
| `src/momentum/api/data_mode.py` | demo-exclusion filter, `is_production`, `purge_demo_rows`, `count_demo_rows` | **Production guard** | the machinery that excludes/purges demo rows in production |
| `src/momentum/universe/membership.py:24` `_EMBEDDED_MEMBERS` | 96-ticker default universe | **Onboarding** | the shipped tradeable universe when no config/override exists — **live data**, not demo |
| `config/*.example.yaml` | shipped config defaults | **Onboarding** | copied to the user dir on first run; tunables, not market data |
| `src/momentum/data/providers/*.py` (docstring "MockTransport") | testability note | **Testing** | providers are documented as testable with `httpx.MockTransport`; no mock in the runtime path |
| `tests/**`, `conftest.py` factories, `seed_all` calls in tests | fixtures / stubs / seeds | **Testing** | offline determinism (in-memory SQLite, stub providers, seeded RNG) |
| `app.state.provider_factory`, synchronous job runner | DI seams | **Testing** | let tests inject a stub provider / inline runner; production uses `build_provider` + real `JobManager` |
| `resolve_active_run_id` / `_winning_batch` "demo fallback" | read fallback to the `demo` run | **Onboarding** | only when **no live scan exists**; in production the demo rows are filtered out, so the fallback resolves to `None`, never demo |
| `tradeplan`/`options` `fallback_*` vol, EMA fallback | numeric fallbacks | **n/a** | unrelated to demo data (default vol / structure) |

### Accidentally reachable in production
**None remain.** Every path that could put demo data on a production screen is closed:

| Path | Status |
|---|---|
| `seed_all` called directly | **Guarded** — raises in production (the single chokepoint, `demo.py:517`) |
| `seed_demo_data` action / `/actions/seed-demo` | Guarded — raises / refused |
| `/actions/reset?load_demo` | Guarded — 409 in production |
| Demo rows read by a screen | Excluded by the global `do_orm_execute` filter (`with_loader_criteria`) in production |
| `resolve_active_run_id` demo fallback | Demo rows filtered in production → fallback returns `None`, not the demo run |
| Demo rows lingering in a DB switched to production | Purged on switch **and** at every production startup (`create_app`), then asserted zero |

## Guards implemented

1. **Production builds can never read demo data** — the global SQLAlchemy
   `do_orm_execute` listener (`data_mode`) appends `with_loader_criteria` excluding
   `run_id == "demo"` (and `market_regimes.model_version == "demo"`) from **every** ORM
   SELECT when production mode is active. Opt-out per statement via
   `execution_options(include_demo=True)` (only the purge/count use it).

2. **Demo loading is impossible in production** — `demo.seed_all` (the core
   chokepoint) raises `RuntimeError` in production; `seed_demo_data`, the
   `/actions/seed-demo` and `/actions/reset?load_demo` paths all refuse.

3. **Startup assertion** — `create_app`, when production mode is active, **purges**
   any demo rows and then **asserts `count_demo_rows() == 0`**, aborting startup with
   a clear error if any remain. So a production process can never serve demo data.

## Tests (`tests/unit/api/test_production_guards.py`)

- `test_seed_all_refused_in_production`, `test_seed_demo_action_refused_in_production`
- `test_production_startup_purges_demo` — boot with demo rows present → purged, count 0
- **`test_production_scan_cannot_return_seeded_symbols`** — `GET /scan` returns only the
  live run, zero demo `scan_results`
- **`test_production_watchlists_cannot_use_seeded_data`** — live watchlists, zero demo rows
- **`test_production_conviction_cannot_use_seeded_data`** — `GET /conviction` only the live run

All pass; the broader `tests/unit/api/test_data_mode.py` continues to cover the filter +
purge invariants.
