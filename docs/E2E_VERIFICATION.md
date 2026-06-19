# End-to-End Verification Checklist

How to verify the whole paper-trading path works — from a database connection to
a full daily orchestration run. Three layers: a **pass/fail checklist**, the
**automated tests** that back each item, and a **manual workflow** for a human.

## Pass/Fail checklist

| # | Stage | What "pass" means | Automated check |
|---|---|---|---|
| 1 | **Database connection** | Engine connects; schema has every table | `verify_e2e.py` · `test_database_connection_and_schema` |
| 2 | **Data ingestion** | Bars write to the cache and read back unchanged (idempotent) | `test_data_ingestion_cache_round_trip` |
| 3 | **Scanner** | `MomentumScanner.scan` ranks ≥1 candidate from bars | `test_scanner_ranks_candidates` |
| 4 | **Conviction engine** | Strong setup scores higher than weak; bands assigned | `test_conviction_engine_scores_and_bands` |
| 5 | **Risk engine** | Proposal is sized, stopped and approved | `test_risk_engine_sizes_and_vets` |
| 6 | **Paper orders** | `PaperBroker` fills at reference ± slippage with fees | `test_paper_broker_fills_order` |
| 7 | **Position tracking** | `Portfolio` updates cash/equity and bridges to risk | `test_position_tracking_updates_portfolio` |
| 8 | **Trade journal** | Open + close persist to `trades` with correct P&L | `test_trade_journal_persists_open_and_close` |
| 9 | **Audit logs** | Events recorded, immutable, queryable, timestamped | `test_audit_log_records_and_queries` |
| 10 | **Daily orchestration** | `run_day` opens, journals, audits, records the run | `test_daily_orchestration_full_flow` |

Copy/paste for a manual sign-off:

```
[ ] 1. Database connection
[ ] 2. Data ingestion
[ ] 3. Scanner
[ ] 4. Conviction engine
[ ] 5. Risk engine
[ ] 6. Paper orders
[ ] 7. Position tracking
[ ] 8. Trade journal
[ ] 9. Audit logs
[ ] 10. Daily orchestration
```

## Automated tests

**One command, full checklist** (runs every stage against a freshly *migrated*
throwaway SQLite DB and prints PASS/FAIL; exits non-zero on any failure):

```bash
python scripts/verify_e2e.py
```

Expected output:

```
End-to-End Verification Checklist
============================================================
[PASS] database + migrations    migrated → head at verify.db
[PASS] data ingestion           cached + read 300 bars (round-trip)
[PASS] scanner                  ranked 2 candidate(s)
[PASS] conviction engine        score 84.0 band high
[PASS] risk engine              approve 150 sh @ stop 95.00
[PASS] paper orders             filled 100 @ 100.1000
[PASS] position tracking        equity 100,499.00, 1 open position
[PASS] trade journal            persisted trade #1 (status open)
[PASS] audit logs               recorded strategy_change (immutable, queryable)
[PASS] daily orchestration      run paper-20260202: opened 1, equity 99,998
============================================================
10/10 checks passed
```

**Pytest suite** (the per-stage assertions, in-memory, deterministic):

```bash
PYTHONPATH=src python -m pytest tests/integration/test_end_to_end.py -v
```

The complete quality gate (lint + types + all unit/integration tests + migration
drift) remains:

```bash
make check
```

## Manual testing workflow

For a human verifying a real, running instance.

1. **Install & migrate**
   ```bash
   make install
   alembic upgrade head            # creates data/momentum.db with all tables
   ```
   *Verify:* `alembic current` shows revision `0009`.

2. **Run the automated checklist**
   ```bash
   python scripts/verify_e2e.py
   ```
   *Verify:* `10/10 checks passed`.

3. **Inspect the database directly**
   ```bash
   sqlite3 data/momentum.db ".tables"
   ```
   *Verify:* you see `trades`, `runs`, `audit_log`, `scan_results`,
   `conviction_scores`, etc.

4. **Start the read-only API**
   ```bash
   python -m momentum.api        # binds 127.0.0.1:8000
   ```
   In another shell:
   ```bash
   curl -s http://127.0.0.1:8000/health
   ```
   *Verify:* a healthy JSON response (HTTP 200).

5. **Spot-check a queried audit trail / trades** (after a paper run has written
   rows) via the API routes or:
   ```bash
   sqlite3 data/momentum.db "SELECT event_type, summary FROM audit_log ORDER BY id DESC LIMIT 10;"
   sqlite3 data/momentum.db "SELECT symbol, status, net_pnl FROM trades ORDER BY id DESC LIMIT 10;"
   ```

## Notes

- All automated checks are **offline and deterministic** — no network, no real
  broker, no real clock (synthetic bars, in-memory or temp SQLite, fixed
  timestamps).
- `scripts/verify_e2e.py` exercises the **real Alembic migrations** (not
  `create_all`), so it also verifies the migration path end to end.
- SQLite returns tz-naive datetimes on read; checks compare wall-clock values
  accordingly. This is a SQLite characteristic, not a data error.
