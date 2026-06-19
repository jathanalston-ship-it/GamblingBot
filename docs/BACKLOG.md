# Backlog

Deferred / future work, parked here so sessions don't re-discover it. Move an
item into a subsystem doc when it becomes active.

## Known follow-ups

- **Stale remote branch** — `claude/admiring-feynman-n8rhuj` still exists on the
  remote; the managed git proxy returns 403 on ref deletes and the GitHub MCP
  has no delete-branch tool. Delete it from the GitHub UI. All its commits are
  contained in `claude/vigilant-wozniak-oueczq`.
- **Options pricing** — instrument-selection structures use the ATM premium
  approximation (`0.4·S·σ·√T`); swap in real option quotes at execution time.
- **Live option/IV feed** — `InstrumentContext` (IV, OI, spread, LEAPS
  availability) is supplied by the caller; wire a provider for these.
- **Plotly tearsheet** — `reporting/{plots,tearsheet,report_generator}.py`
  remain stubs; the markdown dashboard + research report cover the core today.
- **Remaining stubs** — `execution/` (`order_manager`, `live_broker`, `fills`),
  `orchestration/scheduler.py`, parts of `portfolio/` (`allocator`,
  `rebalancer`), `api/` and `cli/` are documented stubs.

## Paper-slice / orchestration follow-ups

- **Live data/scan source + `mrp paper-run` CLI** — the orchestration engine
  consumes a caller-supplied `ScanResult` + `marks` dict; wire a data/scan source
  and a thin CLI that runs `Scheduler.run_session` and prints the `DailyReport`.
- **Order/position/fill persistence** — only the journal (`trades`) and the
  `runs` registry are persisted; add an orders/positions/fills schema for a full
  execution audit trail.
- **Richer exits** — partial scale-outs and trailing stops (`ExitManager`
  currently does full-position stop/target/time exits only).
- **Live broker adapter & a real scheduler/clock loop** — the `Scheduler` is a
  serial decision point triggered by the caller, not a timed daemon.

## Conventions for this file

One line per item: what + where + why deferred. Keep it short; delete done items.
