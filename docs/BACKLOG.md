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

## Paper-slice follow-ups

- **Exit pass in the pipeline** — `DailyPaperPipeline` only opens entries;
  `TradeJournal.close_trade` / `Portfolio` already support closing. Add a stage
  that exits on stop/target/signal and marks-to-market each session.
- **Order/position/fill persistence** — only the journal (`trades`) is persisted;
  add an orders/positions/fills schema + migration `0008` for a full audit trail.
- **`mrp paper-run` CLI** — a thin entry that loads configs + a scan and runs the
  pipeline, printing the `PipelineReport`. Needs a scan/data source wired first.
- **Append-only audit log, live broker adapter, scheduler/recovery** — the
  remaining "missing layers"; the paper slice intentionally skips them.

## Conventions for this file

One line per item: what + where + why deferred. Keep it short; delete done items.
