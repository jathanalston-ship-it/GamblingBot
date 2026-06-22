# Backend Exception Diagnostics

Never debug another blind 500. Every unhandled backend exception is captured —
**route, stack trace, request parameters, timestamp** — written to the log **and**
served from `GET /diagnostics/recent-errors`, surfaced in the desktop app at
**Settings → Diagnostics**.

## How it works

The global FastAPI exception handler (`api/app.py`) already turns a 500 into a
real `{type}: {message}` body. It now also:

1. builds an `ErrorRecord` (`api/diagnostics.build_record`) from the request + the
   exception, and
2. appends it to an in-memory, bounded `ErrorRecorder` (the last **50**) on
   `app.state.error_recorder`, and
3. logs the full context with `log.exception(...)` — `[route=…] query=… path_params=…`
   plus the stack trace.

Everything captured is run through `core.secrets.redact_text`, so a secret value
can never leak into the buffer, the endpoint or the log.

```
unhandled exception
   → @app.exception_handler(Exception)
        ├─ build_record(request, exc)        (route, trace, params, ts — redacted)
        ├─ app.state.error_recorder.record(…)  (ring buffer, last 50)
        ├─ log.exception("unhandled %s on %s %s [route=%s] query=%s …")
        └─ 500 {detail, path}
   ← GET /diagnostics/recent-errors  → the last 50, newest first
```

Captured per the requirement:

| Requirement | Field |
|---|---|
| 1. Written to logs | `log.exception(...)` (stack trace + enriched message) |
| 2. Route name | `route` (endpoint fn name) + `route_path` (template) |
| 3. Stack trace | `traceback` (full `format_exception`) |
| 4. Request parameters | `query_params` + `path_params` |
| 5. Timestamp | `ts` (ISO-8601 UTC) |

## API

### `GET /diagnostics/recent-errors?limit=50`

The most recent unhandled exceptions, **newest first** (`limit` 1–200, default 50).

```jsonc
{
  "count": 1,
  "capacity": 50,
  "errors": [
    {
      "ts": "2026-06-22T07:52:45.941509+00:00",
      "method": "GET",
      "path": "/_demo_boom",
      "route": "boom",
      "route_path": "/_demo_boom",
      "status": 500,
      "exc_type": "ZeroDivisionError",
      "exc_message": "division by zero in expectancy calc",
      "query_params": { "symbol": "TSLA", "run_id": "demo" },
      "path_params": {},
      "traceback": "Traceback (most recent call last): … ZeroDivisionError: …"
    }
  ]
}
```

### `DELETE /diagnostics/recent-errors`

Clears the buffer (the Diagnostics screen's **Clear** button). Returns `204`.

## Desktop — Settings → Diagnostics

A **Diagnostics — Recent Backend Errors** card (`components/DiagnosticsPanel.tsx`):
each row shows status · exception type · message · `METHOD path · route` · time;
expand a row for the **parameters** table and the full **stack trace**.
**Refresh** re-fetches; **Clear** empties the buffer. Empty state explains that 500s
appear automatically.

## Design notes

- **In-memory, bounded, thread-safe** (`collections.deque(maxlen=50)` + a lock).
  Ephemeral process state — cheap, reset on restart; no persistence/schema.
- **Only genuine 500s are recorded.** A handled `HTTPException` (e.g. a 404) is not
  an unhandled exception and is not added to the buffer.
- **Secret-safe.** All captured strings (message, params, trace) pass through the
  secret redactor (`docs/SECRETS.md`).
- **Always wired.** `create_app` puts an `ErrorRecorder` on `app.state`; the route
  is defensive if one is somehow absent.

## Tests

`tests/unit/api/test_diagnostics.py`: ring-buffer bound/order/limit/clear; a real
500 through the global handler is captured with route + trace + params + timestamp;
empty-when-healthy; newest-first + limit; the clear endpoint; **secret redaction**;
a 404 is **not** recorded; and the route is registered.
