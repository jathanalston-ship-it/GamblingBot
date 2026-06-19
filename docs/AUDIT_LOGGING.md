# Audit Logging

An append-only, immutable record of every material action the platform takes —
the system's authoritative "what happened, and when" history.

## Events (`AuditEvent`)

`signal_generated`, `order_submitted`, `order_filled`, `position_opened`,
`position_closed`, `risk_adjustment`, `strategy_change`, `backtest_run`.

## Guarantees

- **Immutable** — `AuditLogRepository` exposes only `append` and reads; `delete`
  is overridden to raise, and there is no update path. Rows are never mutated.
- **Timestamped twice** — `ts` is the logical event time (the decision/fill
  time, supplied by the caller → deterministic in tests); `created_at` is the
  database write time (server clock).
- **Queryable** — indexed by `event_type`, `ts`, `run_id`, `symbol` (plus
  composite `(event_type, ts)` and `(run_id, event_type)`); the repository offers
  `by_event`, `by_run`, `by_symbol`, `between`, `recent`.
- **Crash-safe** — each event is appended and flushed one at a time, so an event
  already recorded survives a later failure. Payloads are JSON-sanitised
  (datetimes/enums → primitives) so a write never fails on serialization.

## Components

- **`core/enums.py` — `AuditEvent`**: the closed set of recordable actions.
- **`persistence/models/audit_log.py` — `AuditLog`**: the `audit_log` table
  (migration `0009`): `event_type`, `ts`, `run_id`, `symbol`, `entity_type`,
  `entity_id`, `summary`, `payload` (JSON), plus `created_at`/`updated_at`.
- **`persistence/repositories/audit_log.py` — `AuditLogRepository`**: append-only
  access + the query methods.
- **`persistence/audit.py` — `AuditRecord` / `AuditLogger`**: the value object and
  the service with one method per event, each serialising the relevant domain
  object into the payload.

## Wiring

The `DailyOrchestrationEngine` builds an `AuditLogger` per run (toggle with
`enable_audit`, default on) and threads it into the `DailyPaperPipeline`. A single
session therefore records the full trail:

- **Entries:** `signal_generated` → `risk_adjustment` → `order_submitted` →
  `order_filled` → `position_opened`.
- **Exits:** `order_submitted` → `order_filled` → `position_closed`.

`strategy_change` and `backtest_run` are recorded by their respective callers via
the same logger.

## Usage

```python
audit = AuditLogger(AuditLogRepository(session))
audit.order_filled(order, fill, run_id="paper-20260105")
trail = AuditLogRepository(session).by_run("paper-20260105")
```

## Limitations

- Immutability is enforced at the access layer (no DB trigger); direct ORM writes
  bypassing the repository are not prevented.
- `strategy_change` / `backtest_run` are available on the logger but only emitted
  where a caller invokes them (the backtester/strategy-config paths can adopt
  them as they mature). See `docs/BACKLOG.md`.
