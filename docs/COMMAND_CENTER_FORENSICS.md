# Forensic Audit — `GET /command-center` 500

**Symptom:** backend `/health` is healthy, but the desktop landing page shows
`500 Internal Server Error — GET /command-center`.

**Root cause:** a missing database **column** on an upgraded/live desktop DB —
`portfolio_snapshots.daily_pnl` — which a Command Center query selects. Command
Center fired ~10 independent queries with **no resilience**, so a single
schema/data gap 500'd the entire page. **Fixed:** every section is now guarded and
degrades to an empty value; Command Center never 500s on missing data.

## Trace (UI → API client → route → service → repository → DB)

| Layer | Code | Behaviour |
|---|---|---|
| UI | `desktop/.../views/CommandCenter.tsx` | auto-selects a `run_id` (e.g. `demo`) and calls the API |
| API client | `renderer/src/api/client.ts` `apiGet("/command-center?run_id=…")` | `fetch`; throws on non-200 |
| Route | `api/routes/command_center.py` → `get_command_center` | `response_model=CommandCenterOut`; calls the service |
| Service | `api/command_center.py` `command_center()` | aggregates ~10 sections via sub-services + direct queries |
| Repository / query | `select(PortfolioSnapshot)…` (and others) | SQLAlchemy emits `SELECT … daily_pnl …` |
| DB | SQLite (desktop) | **`no such column: portfolio_snapshots.daily_pnl`** → raises |

The app's global exception handler (`api/app.py`) then returns the real error as the
500 detail.

## The seven questions

1. **Exact exception?** `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError)
   no such column: portfolio_snapshots.daily_pnl` → surfaced by the route as a 500.
2. **Missing table?** Not in the reported case, but it is an equivalent trigger (a
   dropped/never-created table 500s the same way) — now also handled.
3. **Missing column?** ✅ **Yes — the root cause.** `select(PortfolioSnapshot)`
   names every model column; if the file predates the `daily_pnl` addition the
   `SELECT` fails. `reconcile_schema` adds missing **nullable** columns but **skips
   non-nullable-without-default** ones, so drift can still surface here.
4. **Missing seed data?** No — an empty DB returns a valid empty-state 200.
5. **Invalid run_id?** No — `_effective_run_id` already falls back to latest; an
   unknown/blank run id returns 200.
6. **Null handling failure?** No — nulls are handled; floats are now sanitised.
7. **Serialization failure?** Not the trigger (Pydantic v2 serialises inf/NaN →
   null), but the directly-DB-sourced floats are now passed through `_finite()` as
   defence-in-depth (matching the `/watchlists` fix).

## Full stack trace (reproduced)

```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such column: portfolio_snapshots.daily_pnl
[SQL: SELECT portfolio_snapshots.run_id, …, portfolio_snapshots.daily_pnl, … FROM portfolio_snapshots
      ORDER BY portfolio_snapshots.session_date DESC LIMIT ? OFFSET ?]
  at command_center._portfolio → session.scalars(select(PortfolioSnapshot)…).first()
  at api/routes/command_center.get_command_center
→ api/app global handler → HTTP 500 {"detail": "OperationalError: … no such column …"}
```

## Fix

`api/command_center.py` rewritten around a resilience contract:

- **`_safe(session, label, fn, default)`** runs each independent section; on **any**
  exception it logs a warning (with traceback, for diagnosis) and returns the
  section's empty default — and **rolls the session back** so one failed query can't
  poison the connection for the remaining sections.
- Sections guarded: run-id resolution, regime, watchlists (the three horizons +
  best reward:risk), highest conviction, top sector, portfolio (heat/equity/daily
  P&L), performance, watchlist changes, recently-triggered.
- A failed section degrades to `None` / `[]`; `performance` (a required field) falls
  back to a zeroed `CommandPerformanceOut`. The response **always** validates.
- Directly-DB-sourced floats (`portfolio_heat`, `equity`, `daily_pnl`, sector
  `avg_conviction`) pass through `_finite()` (non-finite → `null`).

**Result:** `GET /command-center` returns a valid response (empty-state where data
is absent) regardless of schema/data gaps — it never 500s because data is missing.
The underlying schema drift is still logged (so it remains diagnosable and a real
migration/`reconcile_schema` can fix it), but it no longer takes down the page.

## Verification (all 200, valid JSON)

| State | no run_id | run=demo | run=missing |
|---|---|---|---|
| **Fresh install / empty DB** | 200 ✓ | 200 ✓ | 200 ✓ |
| **Seeded database** | 200 ✓ | 200 ✓ | 200 ✓ |
| **Live (non-finite values)** | 200 ✓ | 200 ✓ | 200 ✓ |
| **Upgraded DB, missing column** (the repro) | 200 ✓ | 200 ✓ | 200 ✓ |
| **Missing table** (schema drift) | 200 ✓ | 200 ✓ | 200 ✓ |

Regression tests: `tests/unit/api/test_api.py` —
`test_command_center_empty_db_returns_valid_empty_state`,
`test_command_center_survives_missing_column`,
`test_command_center_survives_missing_table` (+ the existing aggregate/fallback
tests). Full suite: 1062 passed; mypy `--strict` + ruff clean.
