# Production Readiness Audit — 2026-07-03

Scope: the entire application, audited as if it managed real capital.
Method: **execute, don't assume** — the full quality gate, a new adversarial
break-attempt suite (`tests/unit/audit/test_production_readiness.py`, 12
executed scenarios), and a live end-to-end exercise of the real backend
process (real HTTP, real SQLite file, real signals). Every claim below is
backed by an executed command or test.

## Verdict

**READY — for its designed production use: automated *paper* trading.**

This is not a live-capital system and refuses to be one by construction:
the only broker integrations are the internal simulated venue and Alpaca's
*paper* endpoint (base URL pinned to `paper-api.alpaca.markets`). Within
that scope, every subsystem passed verification, one real defect was found
and fixed during the audit, and the known limitations are enumerated below
— none of them silent.

## 1. Baseline quality gate (executed)

| Check | Result |
| --- | --- |
| `ruff format` + `ruff check src tests` | clean |
| `mypy --strict src/momentum` | 0 errors, 384 source files |
| `pytest tests` | **1596 passed** (1584 pre-audit + 12 new break-attempts) |
| `alembic check` (temp DB upgraded to head) | "No new upgrade operations detected" |
| Desktop `npm run typecheck` + `npm run build` | clean, built |
| Desktop node suites (`desktop/scripts/*.test.cjs`) | 57/57 |

## 2. Break attempts (all executed, `tests/unit/audit/test_production_readiness.py`)

| Attack | Result |
| --- | --- |
| Total provider outage mid-scan | Scan raises loudly ("no market data"), zero partial rows, no completed run; next scan recovers fully |
| Partial provider outage (2 of 4 symbols die) | Survivors are scanned; failures logged, never silent |
| Provider dies mid-scan (after N successful calls) | Survivable; no torn persistence |
| Disk full during heartbeat write | Never kills the scan loop (log-only) |
| Disk full during database write (`max_page_count` cap) | Fails loudly ("disk is full"); next scan after space frees completes |
| Corrupt database (512 garbage bytes mid-file) | `check_integrity` reports not-ok; queries raise — corruption is detected, never trusted |
| Power loss mid-state-write (torn JSON) | Survivable: unreadable state degrades to first-run; heartbeat repairs; no `.tmp` litter |
| Garbage `settings.yaml` | Degrades to defaults, never crashes startup |
| 10 duplicate scans, same `run_id` | Zero row growth — idempotent by natural key |
| Weekend / closed market with autopilot ON | Zero automated entries; Saturday is never a scanning state |
| Extreme clock drift (2 h) | `clock_sync` critical → overall critical → autopilot start refused |
| 100 random venue operations (seeded) | Cash conservation holds: cash == starting − open cost + realized − fees (± $1) |

## 3. Live end-to-end (real backend process, fresh DB)

- `GET /health/routes` in-process probe of **140 routes**:
  `server_errors: 0, failed: 0, timeouts: 0, healthy: true`.
- Full user flow: seed demo → command center → settings → brokerage
  account → order placed → `working` → cancelled.
- **Genuine offline preflight refusal** (sandbox blocks Yahoo):
  `PUT /settings/autopilot {"enabled": true}` → HTTP 409
  "Auto Pilot not started — preflight failed: internet: cannot reach
  query1.finance.yahoo.com within 3s; data_provider: provider 'yfinance'
  unreachable — no market data" — and `enabled` stayed `false`.
- Duplicate launch on the same port → exit 1, "address already in use"
  (plus the Electron single-instance lock in the desktop shell).
- `SIGTERM` → `clean_shutdown: true` persisted; backend log free of
  errors/tracebacks; SQLite running in WAL mode.
- **Live power-loss recovery**: staged a stale unclean heartbeat, booted the
  real backend → `GET /automation/recovery` returned
  `recovered_this_startup: true`, downtime 143 524 s, `missed_scans: 1500`
  (capped, market-hours-sampled).

## 4. Issues found

| # | Issue | Severity | Likelihood | Fix | Verification |
| --- | --- | --- | --- | --- | --- |
| 1 | `automation_state._write` was non-atomic — power loss mid-write could tear the heartbeat file exactly when the recovery record matters most | Low | Low | **FIXED**: write to `.json.tmp` + `os.replace` (atomic on POSIX & Windows) | `test_torn_state_file_after_power_loss_is_survivable` (truncated JSON → survivable; no tmp litter) |
| 2 | `tests/unit/api/test_scan_rejections.py` failed once in one full-suite run (2 tests), passed in isolation and in two subsequent full runs | Low | Rare | Not reproducible in 3 attempts; recorded in `docs/BACKLOG.md` for a test-isolation sweep | Two clean full-suite runs (exit 0) after the observation |

## 5. Known limitations (documented, not silent)

- **Electron binary smoke is unrunnable in this sandbox** (binary download
  blocked). Covered by CI on every push (`desktop.yml`: xvfb smoke boots the
  built app and asserts it paints) and by the release pipeline's
  seven-criteria packaged-launch validation, which gates publishing.
- **Onedir frozen backend** is validated by the Windows release pipeline
  (`release-validation.cjs`), not locally on Linux.
- **CLI dual-instance**: two `mrp serve` processes on *different* ports can
  share one DB. Mitigated by WAL + idempotent persistence + the desktop
  single-instance lock; accepted risk for CLI power users.
- **Fills are simulated** at scan prices crossing a modeled spread — honest
  for paper trading, and stated everywhere; there is no live order book.
- OS-level power-blocker release on a hard kill is the OS's documented
  behavior (blocker dies with the process) — asserted in unit tests via the
  injectable blocker, untestable end-to-end in CI.

## 6. Re-running this audit

```bash
make lint && make test                                   # gate
PYTHONPATH=src python -m pytest tests/unit/audit -q      # break attempts
```

The live E2E is manual by nature: boot `python -m momentum.api` against a
scratch `MRP_USER_DIR`, then walk §3's probes.
