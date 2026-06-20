# Signal Evaluation System

Grades every generated signal against its realised outcome — **was the conviction
warranted, and was the predicted move right?** — and rolls the answers up into
calibration, signal-quality and conviction-accuracy dashboards.

## Per-signal tracking

Each signal is joined to the trade it produced (`Trade.entry_signal_id`), its
conviction (the prediction) and the daily watchlist's expected move:

| Tracked | Source |
|---|---|
| Outcome (win / loss / open / none) | the linked trade's R |
| Max Favorable / Adverse Excursion | trade `mfe` / `mae` (R) |
| Holding Period | trade `holding_days` |
| Return | trade `return_pct` (the actual move) |
| Risk/Reward | realised excursion efficiency `mfe / |mae|` |

This is **derived on demand** (no new table) — the outcome already lives on the
trade; evaluation is a join + metrics.

## Comparisons

- **Predicted Move vs Actual Move** — watchlist expected move vs the trade's
  realised return: mean predicted, mean actual, mean absolute error, bias.
- **Predicted Conviction vs Actual Outcome** — conviction buckets vs the realised
  win rate (the calibration curve).

## Generated metrics

- **Calibration** — five conviction buckets (0-20 … 80-100): count, average
  predicted probability (conviction/100), actual win rate, average R. A perfectly
  calibrated model sits on the diagonal.
- **Signal Quality** — win rate, expectancy (R), profit factor, average MFE/MAE,
  **E-ratio** (avg MFE / avg |MAE| — excursion efficiency), payoff ratio, average
  holding and return — overall and **by source** and **by signal type**.
- **Conviction Accuracy** — `rank_auc` (P(winner's conviction > loser's)),
  Pearson correlation (conviction vs R), Brier score (conviction as a probability),
  and whether the win rate is **monotonic** across conviction buckets.

`signaleval/engine.py` is a pure `list[EvaluatedSignal] -> SignalEvaluationReport`
(reusing `analytics.statistics`); the service sanitises non-finite metrics to
`null`.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/signal-evaluation` | Calibration + quality + accuracy dashboard payload. |
| `GET` | `/signal-evaluation/signals` | Per-signal rows (signal + realised outcome). |

## Desktop

The **Signal Eval** view (left rail) shows the quality headline, a **calibration
plot** (predicted vs actual, against the diagonal) + table, conviction-accuracy
and predicted-vs-actual-move stat blocks, quality **by source / by type**, and a
per-signal table. The demo links an entry signal to every trade so the dashboards
populate from sample data.
