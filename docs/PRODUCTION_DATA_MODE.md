# Production Data Mode

A persisted **data mode** that guarantees a scan — or any screen — can never
display seeded (demo) data. The fix for the shadowing risk catalogued in
`docs/DATA_FLOW_AUDIT.md`.

## Modes

| Mode | Meaning |
|---|---|
| **Demo** (default) | Sample data is allowed. The demo seeder populates every screen; demo rows (`run_id="demo"`, regimes `model_version="demo"`) are visible. Existing behaviour. |
| **Production** | Live data only — Yahoo, the database, and live scan results. Demo seeding is **disabled**, existing demo rows are **purged**, and **every read excludes demo rows** even if some remain. |

Set it in **Settings → Data Mode**, or `PUT /settings/data-mode {"mode": "production"}`.

## How the guarantee is enforced (one rule, not 12 patches)

The audit found that ~12 screens each read the DB with queries that filter
`run_id` only when one is supplied — so demo could shadow live. Rather than patch
every query, production mode installs **one unbypassable filter**:

- **Global query filter** (`src/momentum/api/data_mode.py`) — a SQLAlchemy
  `do_orm_execute` listener registered on `Session`. When production mode is
  active it appends `with_loader_criteria` to **every ORM `SELECT`** so that:
  - models with a `run_id` column return only rows where `run_id IS DISTINCT FROM
    "demo"` (keeps live `run_id` values **and** `NULL`), and
  - `market_regimes` (no `run_id`) returns only rows where `model_version IS
    DISTINCT FROM "demo"`.

  This covers services, repositories, the command center, watchlists, signal
  eval/audit, replay — every read path, because it operates at the session
  layer. A caller that legitimately needs demo rows (the purge's own accounting)
  opts out per statement with `execution_options(include_demo=True)`.

- **Purge on switch** — selecting production deletes every demo-tagged row across
  all tables (`purge_demo_rows`) and commits, so demo data is gone, not just
  hidden.

- **Seeding disabled** — `actions.seed_demo_data` raises in production, and
  `POST /actions/reset` with `load_demo` returns **409**. Demo data can never
  re-enter a live database.

- **Persistence** — the mode is stored in `settings.yaml` (`data.mode`) and loaded
  into the process flag at app/CLI startup (`load_from_settings`), so it survives
  restarts.

Default is **demo**, so nothing changes until production is explicitly selected
(the entire existing test suite is unaffected).

## API

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/settings/data-mode` | — | `{mode, valid_modes, demo_rows}`. |
| PUT | `/settings/data-mode` | `{mode}` | Set mode; production purges demo rows and returns `{mode, purged, purged_total, demo_rows}`. |

## Verification report

All automated (`tests/unit/api/test_data_mode.py`), plus a live smoke run.

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Demo mode shows seeded data | ✅ | `test_demo_mode_shows_demo_data` — 15 scans / 15 conviction / regime present. |
| 2 | Switching to production **purges** demo rows | ✅ | `test_switch_to_production_purges_demo` — `purged_total > 0`, `count_demo_rows == 0`. |
| 3 | Production **ignores** demo in queries | ✅ | scans / conviction / regime all empty after switch; `test_production_filter_hides_demo_even_if_present` proves a demo row inserted *under* production is still invisible on read. |
| 4 | Production **keeps live** data | ✅ | `test_production_keeps_live_data` — only the `LIVE` symbol + `v1` regime remain. |
| 5 | Demo seeders **disabled** in production | ✅ | `test_seed_blocked_in_production` (raises); reset+demo returns 409. |
| 6 | Mode **persists** + reloads | ✅ | `test_mode_persists_and_reloads` — `load_from_settings()` restores production. |
| 7 | REST surface | ✅ | `test_data_mode_endpoints` — GET/PUT, `/universe/scans` returns `[]` after switch, bad mode → 400. |
| 8 | No regression in demo mode | ✅ | full suite: **1126 passed** (default demo mode unchanged). |

Live smoke (seeded DB, 708 demo rows): switching to production purged all 708;
`list_scans`/`list_conviction` → 0; `latest_regime` → None; re-seed blocked.

### The guarantee

> A scan cannot accidentally display seeded data.

In production mode there is **no code path** by which a `run_id="demo"` (or
`model_version="demo"`) row reaches a screen: such rows are deleted on switch,
and the session-level filter excludes them from every subsequent ORM read unless
a caller explicitly opts in with `include_demo=True` (used only by the purge's own
row count). New demo rows cannot be created because seeding is refused.

## Files

- `src/momentum/api/data_mode.py` — mode flag, global demo-exclusion filter,
  purge, `set_mode`.
- `src/momentum/api/user_settings.py` — `read/write_data_mode` (settings.yaml).
- `src/momentum/api/routes/settings.py` — `GET/PUT /settings/data-mode`.
- `src/momentum/api/actions.py`, `routes/actions.py` — seed/reset guards.
- `src/momentum/api/app.py`, `cli/main.py` — load the mode at startup.
- `desktop/renderer/src/views/Settings.tsx` — Data Mode panel.
- `tests/unit/api/test_data_mode.py` — verification tests.
