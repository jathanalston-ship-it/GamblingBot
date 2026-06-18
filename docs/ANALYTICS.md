# Analytics — Measuring the Right Thing

> **Status: implemented.** Code in `src/momentum/analytics/`; tests in
> `tests/unit/analytics/`.

The analytics layer encodes the platform's optimisation philosophy. The strategy
is **not** tuned for win rate or trade count — it is tuned for a **positive-skew
payoff**. Every summary therefore leads with the objective metrics and treats
win rate, trade count and holding time as diagnostics, never targets.

## The objective

```python
from momentum.analytics import Trade, analyze_performance

report = analyze_performance(equity_curve, trades)
report.objective       # the metrics we maximise
# {'expectancy_r', 'profit_factor', 'avg_winner_r',
#  'largest_winner_r', 'trend_capture', 'payoff_ratio'}
print(report.summary())
```

| Objective metric | Definition |
|---|---|
| **Expectancy** (`expectancy_r`) | Mean R-multiple per trade — the primary edge measure |
| **Profit factor** | Gross profit ÷ gross loss |
| **Average winner** (`avg_winner_r`) | Mean R of winning trades |
| **Largest winner** (`largest_winner_r`) | Best single trade in R |
| **Trend capture** | Σ realised R ÷ Σ favourable excursion (MFE) across winners |
| **Payoff ratio** | Average winner ÷ \|average loser\| (asymmetry) |

### Explicitly accepted (not penalised)

- **Low win rate** — sub-50% is healthy when winners dwarf losers.
- **Long holds** — `winner_loser_hold_ratio` should be ≫ 1 (let winners run, cut losers).
- **Large asymmetry / fat right tail** — surfaced by `payoff_ratio`, `tail_ratio`,
  `r_skew`, and `top5/top10_winner_profit_share` (a few trades should carry the system).

Win rate, trade count and average holding days are still computed — under the
report's **diagnostics**, not its objective.

## Components

| Module | Responsibility |
|---|---|
| `statistics.py` | Pure helpers: expectancy, profit factor, payoff, tail ratio, winner concentration, SQN, skew, streaks |
| `trade_analysis.py` | `Trade` (dollars + R) and `TradeStats` — the objective-first trade summary |
| `metrics.py` | Equity-curve metrics: CAGR, vol, Sharpe, **Sortino** (downside-only, apt for positive skew), Calmar, tail ratio |
| `drawdown_analysis.py` | Underwater curve, max drawdown, duration, recovery, ulcer index |
| `performance.py` | `PerformanceReport` — objective metrics first, equity & drawdown as context; `to_optimization_record()` maps to the `optimization_results` table |

## Worked profile

A deliberately **35% win-rate** system can be excellent here:

```
expectancy            +0.78 R
profit factor          2.19
avg winner             4.07 R
largest winner         9.00 R
trend capture          0.87
payoff asymmetry       4.07x
--- context (not targets) ---
win rate (reported)    35.0%
winners held           50d  vs  losers 8d
```

Sortino is preferred over Sharpe in headline risk-adjusted terms because upside
volatility (large winners) is the *goal*, not "risk" to be penalised.
