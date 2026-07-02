# Daily Orchestration Engine

Runs the full paper-trading session as one cycle and is the **single source of
truth**: it holds no in-memory account state, reconstructing everything from the
persisted trade ledger on each run.

```
recover state → manage exits → run entries → persist run → daily report
```

## Components (`src/momentum/orchestration/`)

- **`engine.py` — `DailyOrchestrationEngine.run_day(...)`** the cycle:
  1. **Recover** — `reconstruct_portfolio` rebuilds the `Portfolio` from the
     `trades` ledger (open positions + derived cash); marks to the day's prices.
  2. **Run marker** — writes a `running` row to the `runs` table (durable).
  3. **Manage exits** — trailing stops are ratcheted first (`stop_adjustments`,
     persisted to `trades.current_stop` so they survive restarts), then
     `ExitManager` evaluates each open position; a triggered stop / trailing
     stop / target / scale-out / time-stop becomes a (possibly partial) paper
     order → portfolio update → `TradeJournal.close_trade` (or
     `TradeJournal.scale_out`, which banks the partial P&L on the open row).
     Every exit order + fill is persisted to `orders`/`fills`.
  4. **Run entries** — delegates to `DailyPaperPipeline` (scan → conviction →
     risk sizing → paper order → position tracking → journal); entry orders are
     persisted too.
  5. **Persist** — flips the run to `completed` (or `failed`) and returns a
     `DailyReport`.
- **`exits.py`** — `ExitConfig` (immutable Pydantic; `config/exits.example.yaml`):
  `use_stop`, `target_r`, `max_holding_days`, plus `trailing_stop_pct` (ratchet
  the stop that fraction below the mark — tightens only, never loosens) and
  `scale_out_r`/`scale_out_fraction` (one partial profit-take at a lower R than
  the full target; fires once, at full size). Pure rules: `trailing_stop` and
  `evaluate_exit` (stop → target-R → scale-out → time-stop, in priority order)
  and `ExitManager` (`stop_adjustments` + `exits`).
- **`recovery.py`** — `reconstruct_portfolio`: cash is derived, not stored, so the
  ledger alone reproduces the live portfolio exactly.
- **`daily_report.py`** — `DailyReport` (equity before/after, opened/closed,
  realised/unrealised P&L, entry-decision tally) as dict or markdown.
- **`scheduler.py`** — `Scheduler`: the single entry point. Skips a session that
  already `completed` (idempotent) unless `force=True`, and surfaces
  `interrupted_runs` left `running` by a crash.

## State persistence & crash recovery

- **Single source of truth:** the `trades` table. Positions and cash are always
  reconstructed from it; nothing lives only in memory.
- **State persistence:** the `runs` table (migration `0008`) records every run's
  mode, session date, lifecycle status, config hash and equity/trade outcome.
- **Crash recovery:** state is committed incrementally and the run is flipped to
  `completed`/`failed`. A crash leaves a `running` row; re-running reconstructs
  from the committed ledger, and the idempotent journal (open dedupe per
  `run_id`+symbol) plus the held-symbol guard prevent double work. On an
  exception the engine rolls back uncommitted work and records the run `failed`.

## Usage

```python
engine = DailyOrchestrationEngine(
    conviction=ConvictionEngine(),
    risk=RiskManager(),
    broker=PaperBroker(ExecutionConfig()),
    starting_equity=100_000.0,
    exit_manager=ExitManager(ExitConfig.from_yaml("config/exits.example.yaml")),
)
report = Scheduler(engine).run_session(
    session, scan=scan_result, marks=close_prices,
    as_of=date(2026, 1, 5), regime=RegimeState.BULLISH,
)
```

## Limitations (out of scope)

- The engine consumes a `ScanResult` and a `marks` dict supplied by the caller;
  wiring a live data/scan source and a `mrp paper-run` CLI is future work.
- Exits are full-position only (no partial scale-outs); no trailing stop yet.
- No live broker, no real scheduler/clock loop (the `Scheduler` is a serial
  decision point, triggered by the caller). See `docs/BACKLOG.md`.
