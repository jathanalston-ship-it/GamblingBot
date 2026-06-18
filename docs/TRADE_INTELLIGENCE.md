# Trade Intelligence Database

> **Status: implemented.** Schema: the `trades` table + migration `0003`
> (`models/trade.py`). Access: `repositories/trades.py`. Analytics:
> `analytics/attribution.py`, `analytics/queries.py`, `analytics/dashboard.py`.
> Raw SQL: `sql/trade_intelligence.sql`. Tests in `tests/unit/`.

Every trade is stored with enough context to answer *why* it happened and *where*
the edge comes from — then sliced, queried and dashboarded. Like the rest of the
platform, every view leads with the objective metrics (expectancy, profit
factor, trend capture) and treats win rate as a diagnostic.

## What is stored (per trade)

| Field | Column(s) |
|---|---|
| Entry | `entry_ts`, `entry_price`, `quantity`, `initial_stop` |
| Exit | `exit_ts`, `exit_price` |
| Holding time | `holding_days`, `bars_held` |
| Maximum Favorable Excursion | `mfe` (in R) |
| Maximum Adverse Excursion | `mae` (in R) |
| Sector | `sector` |
| Volume | `entry_volume` |
| Relative Volume | `entry_relative_volume` |
| Market Regime | `regime_label` (+ `regime_id` FK) |
| Reason for Entry | `entry_reason` (+ `entry_signal_id` FK) |
| Reason for Exit | `exit_reason` |

Outcome columns (`r_multiple`, `gross_pnl`, `fees`, `net_pnl`, `return_pct`) and
linkage (`run_id`, `entry_signal_id`, `position_size_id`, `regime_id`) complete
the record. Migration `0003` adds the intelligence columns and indexes
`sector`, `regime_label`, `entry_reason`, `exit_reason` for fast slicing.

## 1. Analytics reports

`momentum.analytics.attribution` slices a list of trades along every recorded
dimension, each summarised with the objective-first `TradeStats`:

```python
from momentum.analytics import trade_intelligence_report
from momentum.persistence.repositories.trades import TradeRepository

with session_factory() as s:
    trades = TradeRepository(s).analytics_trades(run_id="backtest-2024")
report = trade_intelligence_report(trades)

report.overall.expectancy_r      # headline edge
report.by_sector                 # {sector: TradeStats}, sorted by expectancy
report.by_regime                 # bullish / neutral / bearish
report.by_entry_reason           # which setups actually pay
report.by_exit_reason            # which exits preserve trend capture
report.by_holding_bucket         # do winners run? (0-1d … 60d+)
report.best_sector()             # strongest slice
```

Dimensions are sorted by expectancy (R), so the strongest sector/setup/regime is
first and the worst is last.

## 2. SQL queries

`momentum.analytics.queries.NAMED_QUERIES` holds tested, parameterised SQL
(`:run_id`, `:limit`) over the `trades` table — the same metrics expressed in
SQL for BI tools or the CLI. The identical statements are exported to
`sql/trade_intelligence.sql` for `sqlite3` / `psql` / DBeaver.

```python
from momentum.analytics import run_query

run_query(session, "overall_summary", run_id="r1")
run_query(session, "performance_by_sector", run_id="r1")
run_query(session, "performance_by_exit_reason", run_id="r1")
run_query(session, "top_winners", run_id="r1", limit=20)
run_query(session, "excursion_capture", run_id="r1")   # MFE/MAE & trend capture
run_query(session, "monthly_pnl", run_id="r1")
```

Available queries: `overall_summary`, `performance_by_sector`,
`performance_by_regime`, `performance_by_entry_reason`,
`performance_by_exit_reason`, `performance_by_holding_bucket`,
`performance_by_relative_volume`, `top_winners`, `excursion_capture`,
`monthly_pnl`. Profit factor, expectancy, win rate and trend capture are
computed directly in SQL (CASE-based, so SQLite-portable) and are unit-tested to
match the Python analytics exactly.

## 3. Dashboards

`render_dashboard(report)` produces a dependency-free markdown dashboard —
terminal, file, PR comment or notebook — leading with the objective panel and a
table per dimension:

```python
from momentum.analytics import render_dashboard
print(render_dashboard(report, title="Q1 Book"))
```

```text
# Q1 Book
## Objective (what we optimise for)
- Expectancy: 2.50 R  ($1,875/trade)
- Profit factor: 6.00
- Average winner: 6.00 R  |  Largest winner: 9.00 R
- Trend capture: 0.87  |  Payoff asymmetry: 6.00x
- context — win rate 50%, 6 trades, winners held 1.8x longer than losers

## By sector
| sector | trades | expectancy_R | profit_factor | avg_winner_R | trend_capture | win_rate |
| Tech   | 3      | 6.00         | ∞             | 6.00         | 0.87          | 1.00     |
| Energy | 2      | -1.00        | 0.00          | 0.00         | —             | 0.00     |
```

A richer Plotly tearsheet (`reporting/`) can render the same `report` later; the
text dashboard keeps the core insight portable and testable.

## Flow

```
backtest / live  ──>  trades table (TradeRepository)  ──>  analytics_trades()
                                                              │
              ┌───────────────────────────────────────────────┼───────────────┐
              ▼                         ▼                       ▼
   trade_intelligence_report     NAMED_QUERIES (SQL)     render_dashboard
        (Python attribution)      (BI / sqlite3)          (markdown tiles)
```
