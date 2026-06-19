---
name: add-subsystem
description: Scaffold a new momentum subsystem (engine/package) the way this codebase does it — immutable Pydantic config, frozen-dataclass I/O types, pure logic + thin engine, optional persistence (model + migration + repository), tests, and docs. Use when adding a new engine, selector, analyzer or similar module.
---

# add-subsystem — the repeatable recipe

Every subsystem here (regime, scanner, risk, analytics, backtest, instruments,
reporting) follows the same shape. Mirror an existing one (e.g.
`src/momentum/instruments/` or `src/momentum/risk/`) rather than inventing.

## Steps

1. **Config** — `config/<x>.example.yaml` + `<X>Config` in
   `src/momentum/<pkg>/<x>_config.py`: immutable Pydantic
   (`ConfigDict(frozen=True, extra="forbid")`), `from_yaml`/`from_dict`,
   `config_hash()`, and `@model_validator(mode="after")` ordering checks.
2. **Types** — frozen dataclasses (`frozen=True, slots=True`) for inputs and the
   result object, each with `to_dict()` and (if persisted) `to_record()` that
   maps 1:1 to an ORM table.
3. **Pure logic** — small, pure functions for the maths/scoring (no I/O); reuse
   `analytics.statistics`, `signals.indicators`, `data.schema` where possible.
4. **Engine** — a thin class that wires inputs → pure functions → result. No SQL,
   no vendor calls.
5. **Exports** — list the public surface in the package `__init__.py` `__all__`.
6. **Persistence (if needed)** — ORM model in `persistence/models/`, register it
   in `persistence/models/__init__.py`, then use the `add-migration` skill, then
   a `Repository[T]` subclass in `persistence/repositories/`.
7. **Tests** under `tests/unit/<pkg>/`: pure-function tests, engine scenarios,
   config validation, and (if persisted) an in-memory-SQLite round-trip.
8. **Docs** — `docs/<X>.md`, a row in the README docs table, and a bullet in
   `CLAUDE.md`'s "Implemented so far".

## Conventions to copy

- `from __future__ import annotations`; strict typing; ruff line length 100.
- Objective-first metrics (expectancy / profit factor / trend capture lead;
  win rate is a diagnostic).
- Idempotent persistence (replace per natural key).

Finish by running the `verify` skill (or `make check`), then commit and
`make safe-push`.
