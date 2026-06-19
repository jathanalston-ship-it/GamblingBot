# API Layer

A **read-only** FastAPI service over the MRP research database. It surfaces what
the platform has recorded — signals, trades, regimes, portfolio snapshots, risk
metrics, scans, optimization results and performance summaries — but never
mutates strategy, config or stored research.

## Run

```bash
uvicorn momentum.api.app:create_app --factory --reload
# Swagger UI at http://127.0.0.1:8000/docs ; OpenAPI at /openapi.json
```

`create_app()` builds the engine from `DATABASE_URL` (via the persistence
layer). Tests inject an in-memory session factory: `create_app(session_factory=...)`.

## Endpoints

| Method & path | Query params | Returns |
|---|---|---|
| `GET /`, `GET /health` | — | service/version health |
| `GET /signals` | `symbol`, `run_id`, `limit` | recent signals (with feature context) |
| `GET /trades` | `symbol`, `status`, `run_id`, `limit` | trades (open/closed) with R-multiples |
| `GET /regimes` | `limit` | regime classifications (newest first) |
| `GET /regimes/latest` | — | most recent regime (404 if none) |
| `GET /portfolio/snapshots` | `run_id`, `limit` | equity-curve snapshots (chronological) |
| `GET /risk/metrics` | `scope`, `window`, `run_id`, `limit` | risk/performance metrics |
| `GET /universe/scans` | `run_id`, `passed_only`, `limit` | momentum-scanner results |
| `GET /backtests/optimizations` | `study_name`, `limit` | parameter-study results |
| `GET /performance` | `run_id` | trade stats + (when an equity curve exists) full performance metrics |

## Design

- **Layering:** `routes` (HTTP) → `services` (read-only queries, return Pydantic
  schemas) → persistence repositories / `analytics`. No business logic in routes.
- **Contract:** `schemas.py` Pydantic models are decoupled from the ORM
  (`from_attributes`); the ORM is never exposed directly.
- **Sessions:** request-scoped via `dependencies.get_session`, read from
  `app.state.session_factory` (so tests swap in an in-memory DB).
- **Performance:** `GET /performance` composes `analytics.compute_trade_stats`
  with `analytics.analyze_performance` over the run's equity curve.

Strict-typed (`mypy --strict`) and covered by `tests/unit/api` against a seeded
in-memory database via FastAPI's `TestClient` (no network).
