# Automated Weekly Research Reporting

> **Status: implemented.** Code in `src/momentum/reporting/research_report.py`;
> persistence in the `research_reports` table (migration `0004`,
> `repositories/research_reports.py`); tests in `tests/unit/reporting/`.

Once a week the system reads **everything that happened** — all trades, all
signals, all market regimes for the period — runs the objective-first analytics
and produces an **evidence report**. It then stops. It is the platform's research
analyst, not its operator.

## Two hard guarantees

1. **Read-only.** Generation queries the database and writes *nothing*. The only
   side effect (and only via `run_weekly_report(persist=True)`) is appending one
   `research_reports` row. It never edits strategy, risk or any config/tunable —
   enforced and tested (`test_generation_is_read_only`).
2. **Evidence, not action.** "Potential improvements" are explicitly framed as
   hypotheses for human review and carry a *not auto-applied* disclaimer. There
   is no code path from this module to a strategy/config change.

## What it analyses

| Source | Pulled via | Used for |
|---|---|---|
| **Trades** | `TradeRepository.closed_between` | objective metrics + full attribution (sector / regime / entry-reason / exit-reason / holding) |
| **Signals** | `SignalRepository.between` | counts by status/type, risk-gateway acceptance rate |
| **Market regimes** | `market_regimes` query | regime distribution over the week, latest regime |

## What it generates

* **What worked** — positive expectancy, let-winners-run intact, strong trend
  capture, best sector / setup (by expectancy, min-sample guarded).
* **What failed** — negative-expectancy slices, losses beyond the −1R budget
  (gaps), exits that gave back trend.
* **Largest winners / losers** — top-N trades with full context (R, P&L, holding,
  sector, regime, entry/exit reason).
* **Potential improvements** — evidence-based *hypotheses* (e.g. "investigate
  sector X", "exit Y may be premature — study wider trails"), each tagged for
  human review, never applied.

Everything leads with the objective metrics (expectancy, profit factor, trend
capture); win rate and trade count are reported as context.

## Outputs

| Output | API |
|---|---|
| **Markdown report** | `report.to_markdown()` |
| **JSON report** | `report.to_json()` / `report.to_dict()` |
| **Database record** | `report.to_record()` → `ResearchReportRepository.save` (idempotent per run/period) |

## Usage

```python
from momentum.persistence.database import create_db_engine, create_session_factory, session_scope
from momentum.reporting import generate_weekly_report, run_weekly_report

factory = create_session_factory(create_db_engine())

# generate only (writes nothing):
with session_scope(factory) as s:
    report = generate_weekly_report(s, run_id="live")   # trailing 7 days to today
print(report.to_markdown())
report.to_json()

# generate AND persist the audit record (idempotent per run/period):
with session_scope(factory) as s:
    run_weekly_report(s, period_end=date(2024, 1, 7), run_id="live")
```

### Scheduling

`run_weekly_report` is the weekly entry point — wire it to a cron / scheduler
(e.g. Monday pre-open for the prior week). It defaults to the trailing 7 days
ending `period_end` (today if omitted). Because persistence is idempotent per
`(run_id, period_end)`, a retried or duplicated run replaces rather than
duplicates the record.

## Report shape

```text
# Weekly Research Report — 2023-01-21 to 2023-01-27
> evidence only … read-only … never applied automatically

## Objective metrics      expectancy / profit factor / net P&L / max DD (R) / trend capture
## What worked            bullet evidence
## What failed            bullet evidence
## Largest winners        table (symbol, R, P&L, held, sector, regime, entry, exit)
## Largest losers         table
## Market regimes         distribution + latest
## Signals                status counts + acceptance rate
## Potential improvements  hypotheses — NOT auto-applied
```

The same structure is the JSON `report_json` stored on the `research_reports`
row, so historical evidence is queryable and trendable over time.
