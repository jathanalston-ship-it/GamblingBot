# Development / Factory Reset

A developer-facing maintenance feature (Settings → **Developer — Reset**) that
returns the local application state to a fresh install for rapid testing. Two
hardcoded buttons, each behind an explicit confirmation dialog:

- **Reset Local Data** — wipe everything, then offer a restart.
- **Reset + Load Demo Data** — wipe, re-seed the demo dataset, reload the app.

## What it clears vs. preserves

| Cleared | Preserved |
|---|---|
| Every database row (scans, watchlists, portfolios, conviction, risk metrics, analytics, audit logs, runs, demo data, …) | Application code / binaries |
| Cached market-data parquet (`MRP_BAR_CACHE`) | Database **schema** (tables, columns) |
| Writable user settings (`settings.yaml`) | Alembic **migration history** (`alembic_version`) |
| On-disk logs + startup reports (`MRP_LOG_DIR`) | API keys (`.env`) — unless `preserve_api_keys=false` |

After clearing, the schema is reconciled so every table exists and is **empty**
— i.e. fresh-install state. The backend keeps serving; reads return empty data,
never a 500.

## Endpoint

`POST /actions/reset` — **synchronous** (it stops active jobs as step 1, so it
cannot be a job itself).

```json
{ "load_demo": false, "preserve_api_keys": true }
```

Sequence (`api/reset.py:reset_local_data`): stop active jobs (`JobManager.clear`)
→ `clear_database` (rows only, reverse FK order; `alembic_version` untouched) →
`reconcile_schema` → `clear_bar_cache` → `clear_user_settings` → log the reset
event → `clear_logs` **last**. Returns a summary (rows cleared per table, cache
files removed, logs removed, jobs stopped, and the demo counts when seeded).

The reset event is written to `mrp.log` **before** the logs are cleared.

## Restart

After a plain reset the UI prompts *"Reset complete. Restart Momentum Lab now?"*.
**Restart** calls the preload bridge `window.mrp.relaunch()` → Electron
`app.relaunch(); app.quit()` (graceful backend shutdown, then a fresh process
spawns a new backend and reloads the UI). In a plain browser (no bridge) it falls
back to `window.location.reload()`. **Reset + Load Demo Data** reloads the app
automatically once seeding completes.

## Tests

`tests/unit/api/test_reset.py` proves the contract: **database cleared**, **schema
preserved**, **migration history (`alembic_version`) preserved**, **the app still
serves after reset** (health + reads 200, empty data), **no orphaned rows remain**,
**reset is repeatable**, reset-with-demo repopulates, active jobs are stopped, and
API keys are preserved (or cleared on request). The Electron `relaunch` bridge is
covered by the desktop typecheck/build.
