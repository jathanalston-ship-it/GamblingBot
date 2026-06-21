# API Health Audit

A self-auditing endpoint that **live-probes every API route** and classifies it, so
broken routes are detected automatically rather than by clicking through the UI.

## Endpoint

```
GET /health/routes
```

Returns a classified report of every route the app publishes (enumerated from its
own OpenAPI schema — always in sync with what's mounted):

```json
{
  "total": 55, "passed": 39, "not_found": 3, "server_errors": 0,
  "failed": 0, "timeouts": 0, "skipped": 13, "healthy": true,
  "routes": [
    {"method": "GET", "path": "/watchlists", "classification": "PASS", "http_status": 200, "detail": null},
    {"method": "POST", "path": "/actions/scan", "classification": "SKIPPED", "http_status": null, "detail": "mutating route — not probed"}
  ],
  "generated_at": "…"
}
```

## How it works

For each route it issues a **real request through the full middleware + DB stack**,
in-process via an ASGI transport (no network, no socket). Path params are filled
from samples (`{symbol}`→`AAPL`, `{horizon}`→`daily`, …) and a default query string
satisfies the few routes with required params.

| Classification | Meaning |
|---|---|
| **PASS** | 2xx/3xx — route healthy |
| **404** | reachable, the sample resource doesn't exist (not a defect) |
| **500** | server error — **broken** (the real cause is in `detail`, via the global exception handler) |
| **FAIL** | other 4xx (e.g. 422) — **broken** |
| **TIMEOUT** | no response within the probe timeout — **broken** |
| **SKIPPED** | mutating route (POST/PUT/DELETE) or the audit route itself — not probed (no side effects) |

`healthy` is `true` only when `server_errors == failed == timeouts == 0`.

## Implementation

- **Service** — `api/api_health_service.py` (`audit_routes`): enumerates from
  `app.openapi()`, probes via `httpx.ASGITransport(raise_app_exceptions=False)` so a
  probed 500 returns as a classifiable response instead of re-raising.
- **Route** — `routes/api_health.py` → `GET /health/routes`.
- **Schemas** — `RouteHealthOut`, `ApiHealthReportOut`.
- **Tests** — `tests/unit/api/test_api_health.py`: passes on a healthy app, skips
  mutating/self routes, treats 404 as healthy, and **auto-detects a broken route**
  (a dropped column makes the scan-reading routes classify `500`).

Pairs with the global exception handler (every 500 returns its real error detail),
so the audit's `detail` field names the actual failure for each broken route.
