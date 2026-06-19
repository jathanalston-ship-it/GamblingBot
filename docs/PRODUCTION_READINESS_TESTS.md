# Production-Readiness Test Plan

QA test plan for the Momentum Research Platform under adverse and at-scale
conditions. Implementation is **frozen**; this plan tests current behaviour,
encodes it as automated tests, and records gaps as **findings** (it does not
change product code).

## How to run

```bash
# Everything (unit + integration + robustness + load):
make check

# Robustness + failure injection only:
PYTHONPATH=src pytest tests/robustness -q

# Skip the slow load tests:
PYTHONPATH=src pytest -m "not slow" -q

# Only the load/scale tests:
PYTHONPATH=src pytest -m slow -q

# End-to-end smoke (migrated throwaway DB, prints PASS/FAIL):
python scripts/verify_e2e.py
```

Automated coverage lives in `tests/robustness/test_failure_injection.py`
(20 tests), `tests/robustness/test_load.py` (4 `slow` tests),
`tests/integration/test_end_to_end.py`, and the existing unit suites. Total
suite: **780 tests green**.

## Coverage matrix

| # | Area | Manual | Automated | Failure injection | Load | Status |
|---|---|---|---|---|---|---|
| 1 | Startup failures | ✅ | ✅ | ✅ | — | PASS |
| 2 | Database corruption | ✅ | ✅ | ✅ | — | PASS |
| 3 | Missing data | ✅ | ✅ | ✅ | — | PASS |
| 4 | Invalid market data | ✅ | ✅ | ✅ | — | PASS w/ **FINDING-1** |
| 5 | Empty scans | ✅ | ✅ | ✅ | — | PASS |
| 6 | Large scans | ✅ | ✅ | — | ✅ | PASS |
| 7 | Long-running backtests | ✅ | ✅ | — | ✅ | PASS |
| 8 | Memory leaks | ✅ | ✅ | — | ✅ | PASS |
| 9 | Crash recovery | ✅ | ✅ | ✅ | — | PASS |
| 10 | Audit logging | ✅ | ✅ | ✅ | — | PASS w/ **FINDING-2** |

---

## 1. Startup failures

**Manual**
1. `mrp health` against an unmigrated DB → expect `status: FAIL (missing tables …)`, exit 1.
2. `python -m momentum.api` then `curl /health` → 200 once up.
3. `mrp serve --port <busy>` → uvicorn reports the port conflict and exits non-zero.
4. `mrp scan --provider bogus` → `BadParameter`, non-zero exit, no traceback.

**Automated / failure injection**
- `TestStartupFailures::test_health_fails_on_empty_db` — exit 1, "FAIL".
- `TestStartupFailures::test_cli_rejects_unknown_provider` — non-zero exit.
- `tests/unit/cli/test_cli.py::test_serve_invokes_uvicorn`, `::test_help_lists_commands`.

**Expected result:** no command crashes with a stack trace; misconfiguration
yields a clear message and a non-zero exit code.

## 2. Database corruption

**Manual**
1. Truncate/garble `data/momentum.db`, run `mrp health` → `status: FAIL (DatabaseError…)`, exit 1, **no traceback**.
2. Delete the DB file, run `alembic upgrade head` → schema recreated cleanly.

**Automated / failure injection**
- `TestStartupFailures::test_health_fails_on_corrupt_db` — garbage bytes → exit 1, "FAIL", no "Traceback".
- `TestDatabaseCorruption::test_query_on_corrupt_file_raises` — querying a corrupt file raises a SQLAlchemy `DatabaseError`.
- `TestDatabaseCorruption::test_fresh_db_is_recreated_cleanly` — a new path builds all tables.

**Expected result:** corruption is surfaced as a handled failure, never silent
data loss; a fresh DB is always recoverable via migrations.

## 3. Missing data

**Manual**
1. `mrp paper-run --symbols FAKE1,FAKE2` (delisted/unknown) → run completes, 0 opened, Daily Report prints.
2. Disconnect the network, `mrp scan` → "No candidates" or per-symbol skips, no crash.

**Automated / failure injection**
- `TestMissingData::test_pull_bars_skips_missing_and_erroring` — a provider that errors on one symbol and returns empty for another → only the good symbol survives; the run is not aborted.
- `TestMissingData::test_session_with_no_data_opens_nothing` — empty provider → 0 trades, run still completes.

**Expected result:** a missing/failing symbol is isolated (logged + skipped); it
never aborts the session.

## 4. Invalid market data

**Manual**
1. Feed a CSV missing `volume` → `normalize_bars` raises `SchemaError`.
2. Feed a series with a negative price → `validate_bars(raise_on_error=True)` raises `DataValidationError`.

**Automated / failure injection**
- `TestInvalidMarketData::test_normalize_rejects_missing_columns` — `SchemaError`.
- `TestInvalidMarketData::test_validate_flags_non_positive_prices` — `DataValidationError`.
- `TestInvalidMarketData::test_validate_flags_duplicate_timestamps` — `SchemaError` (non-unique index).
- `TestInvalidMarketData::test_scanner_raises_on_unnormalized_frame` — pins current behaviour.
- `TestInvalidMarketData::test_scanner_ok_when_inputs_are_normalized` — the guard works.

**Expected result:** the validation/schema layer rejects malformed data at the
boundary. **See FINDING-1** for the scanner gap.

## 5. Empty scans

**Manual**
1. `mrp paper-run` on a flat/bearish universe (nothing passes filters) → 0 opened, run completes, report renders.

**Automated**
- `TestEmptyScans::test_scanner_on_empty_bars_returns_empty` — empty `ScanResult`, `candidates == []`.
- `TestEmptyScans::test_engine_on_empty_scan_opens_nothing` — engine opens nothing but records a **completed** run (a no-op day is valid).
- `tests/integration/test_end_to_end.py` exit path drives `make_scan([])`.

**Expected result:** an empty scan is a normal outcome — no error, the day is
recorded.

## 6. Large scans

**Manual**
1. `mrp scan --symbols <500-name list>` → completes in seconds; ranks are dense and ordered.

**Automated / load**
- `tests/robustness/test_load.py::test_large_scan_completes_and_ranks` — 300 symbols × 260 bars, completes < 10 s, ranks unique and sorted.
- `::test_large_pipeline_respects_heat_ceiling` — 150 candidates → only a bounded number open; **portfolio heat ≤ 5%** ceiling holds under load; the rest are budget-rejected.

**Expected result:** scan cost scales linearly; the risk engine's heat ceiling is
never breached regardless of candidate count.

## 7. Long-running backtests

**Manual**
1. Run a multi-year backtest (e.g. 5 000 daily bars) → completes; equity curve has one point per bar (no truncation); no-look-ahead proofs already pass.

**Automated / load**
- `tests/robustness/test_load.py::test_long_backtest_completes` — 5 000-bar (~20 yr) backtest, completes < 15 s, `len(equity_curve) == 5000`, ≥1 trade, positive final equity.
- Existing `tests/unit/backtest/test_no_lookahead.py` — causality proofs (truncating future bars cannot change past results).

**Expected result:** long horizons complete in bounded time and remain
causally correct.

## 8. Memory leaks

**Manual**
1. Run `mrp scan` / a backtest in a loop; watch RSS (`top`/`htop`) → stabilises, does not grow unbounded.

**Automated / load**
- `tests/robustness/test_load.py::test_memory_bounded_across_repeated_scans` — `tracemalloc` around 10 repeated 80-symbol scans → growth < 50 MB (no per-run accumulation).

**Design basis (reviewed):** providers paginate with generators; the backtest
engine stores per-symbol OHLCV as numpy arrays + `{ts: row}` dicts and slices
point-in-time history as `iloc` **views** (`_SymbolData.upto`), not growing
copies; hot value objects are `frozen=True, slots=True`.

**Expected result:** repeated work does not leak; memory is bounded by the
working set, not by run count.

## 9. Crash recovery

**Manual**
1. Kill the process mid `paper-run`; re-run the same `--as-of` → the run row shows the prior `failed`/`running` state, the ledger is consistent, and the re-run completes idempotently (no duplicate trades).
2. `mrp replay --run-id <id>` shows the reconstructed session.

**Automated / failure injection**
- `TestCrashRecovery::test_broker_fault_marks_run_failed` — broker raises mid-entry → run flipped to `failed` with the error, **no partial trade leaked**.
- `::test_rerun_after_failure_recovers` — re-running the same run id with a healthy broker completes.
- `::test_portfolio_reconstructs_from_ledger` — the portfolio is rebuilt from the `trades` table after a simulated restart.
- `::test_interrupted_run_is_surfaced` — a `running` row (crash signature) is reported by `Scheduler.interrupted_runs`.

**Expected result:** the trade ledger is the single source of truth; a crash
leaves a detectable run state and is recovered by an idempotent re-run.

## 10. Audit logging

**Manual**
1. After a `paper-run`, `SELECT * FROM audit_log` → one immutable row per material action, twice-timestamped (`ts` + `created_at`).
2. Attempt to delete an audit row through the repository → refused.

**Automated / failure injection**
- `TestAuditRobustness::test_audit_log_is_append_only` — `repo.delete(...)` raises `NotImplementedError`.
- `TestAuditRobustness::test_audit_trail_complete_for_entry` — an entry records `signal_generated → risk_adjustment → order_submitted → order_filled → position_opened`.
- `tests/unit/persistence/test_audit_log.py` — query by event/run/symbol/between, JSON-sanitised payloads, timestamps.

**Expected result:** every material action is recorded, immutable and queryable.
**See FINDING-2** for the durability nuance.

---

## Findings & risks

| ID | Severity | Finding | Mitigation / recommendation |
|---|---|---|---|
| **FINDING-1** | Medium | `MomentumScanner.scan` raises (`TypeError`) on an un-normalized / malformed bar frame instead of skipping the symbol. In production the data layer normalizes inputs, so it is not hit on the happy path, but a partial/garbled frame slipping through aborts the whole scan. | Defensively `normalize_bars` / `validate` each frame inside the scanner and skip (or quarantine) a bad symbol, mirroring `pull_bars`' provider-error isolation. Pinned by `test_scanner_raises_on_unnormalized_frame`. |
| **FINDING-2** | Low–Med | Audit events are written in the **same transaction** as the work they describe. The engine commits incrementally (so completed steps + their audit persist together), but a deliberate `rollback` discards both the action and its audit row — there is no independent, out-of-band audit channel. | Acceptable for atomic correctness (no audit without the action). If an immutable "attempted but rolled back" trail is required, write audit on a separate connection/session. |
| FINDING-3 | Low | Orders / positions / fills are not persisted (only the `trades` journal + `runs` registry). Intra-run, pre-commit state is memory-only. | Recovery reconstructs from `trades`; add an orders/fills schema if a full execution audit is needed. |
| FINDING-4 | Low | The `slow` load tests add ~11 s to the suite. | Deselect with `-m "not slow"` in fast CI lanes; keep them in the nightly/full gate. |
| FINDING-5 | Trivial | `scripts/*.py` are outside the `mypy --strict` gate (`make check` checks `src/momentum`). | Extend the `check` target to include `scripts/` if desired (both current scripts already type-check clean). |

## Production-readiness sign-off

| Capability | Verdict |
|---|---|
| Starts, fails loudly on misconfiguration | ✅ Ready |
| Survives DB corruption / missing files (no silent loss) | ✅ Ready |
| Isolates missing / failing data | ✅ Ready |
| Rejects invalid data at the boundary | ⚠️ Ready *(harden scanner — FINDING-1)* |
| Handles empty and large scans | ✅ Ready |
| Long backtests complete & stay causal | ✅ Ready |
| Memory bounded under repeated work | ✅ Ready |
| Crash recovery (single source of truth, idempotent re-run) | ✅ Ready |
| Immutable, queryable audit trail | ✅ Ready *(durability nuance — FINDING-2)* |

**Overall:** production-ready for **paper/research** operation, with FINDING-1
recommended before unattended runs over untrusted data feeds. Live trading
remains out of scope (no live broker / order persistence — see `docs/BACKLOG.md`).
