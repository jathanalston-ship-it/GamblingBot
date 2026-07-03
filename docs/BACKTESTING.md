# Backtesting Framework

> **Status: implemented.** Code in `src/momentum/backtest/`; shared cost models
> in `src/momentum/execution/slippage.py`; the time boundary in
> `src/momentum/core/clock.py`. Tests — including the no-look-ahead proofs — in
> `tests/unit/backtest/`.

A deterministic, event-driven backtester whose first design goal is **honesty**:
no look-ahead bias, no future leakage, realistic costs and gap risk. Results feed
the objective-first analytics layer (`docs/ANALYTICS.md`).

## No look-ahead — by construction

Two structural guarantees, each covered by tests:

1. **One-bar decision/fill delay.** A strategy decides on bar *t*'s close; the
   order is filled at bar *t+1*'s **open**. It is impossible to trade on
   information from the same bar you acted on. (`MarketSimulator`, enforced by
   `BacktestEngine`.)
2. **Physically truncated history.** The `StrategyContext` only exposes
   `history(symbol)` up to the current bar — the frame is sliced at the
   `SimulatedClock`'s "now". A strategy *cannot* read a future row because it is
   not in the data it is given.

### The proofs (`tests/unit/backtest/test_no_lookahead.py`)

| Test | What it proves |
|---|---|
| `test_history_never_extends_past_now` | The view's max timestamp always equals `now` — never ahead |
| `test_history_grows_one_bar_at_a_time` | History length is exactly 1, 2, 3, … |
| `test_no_future_column_leak` | The observed price is the *current* close, never a later value |
| `test_decision_cannot_capture_current_bar_move` | A within-bar pop (open→close) is never captured; fill is next open |
| **`test_past_is_independent_of_future`** | **Running on `bars[:N]` vs `bars[:N-10]` yields identical equity on every overlapping bar** — the decisive causality proof |
| `test_trades_before_truncation_are_identical` | Trades closing before a cutoff are bit-for-bit identical regardless of later data |

If a strategy or the engine peeked ahead, the truncation-invariance tests would
fail — past results would shift when future bars were added or removed.

## Realistic frictions

| Concern | Model |
|---|---|
| **Commissions** | `NoCommission`, `PerShareCommission` (per-share + per-order min), `PercentCommission` |
| **Slippage** | `NoSlippage`, `BpsSlippage` (side-aware: buys pay up, sells receive less) |
| **Gap risk** | Protective stops are gap-aware: if a bar *opens* through the stop, the fill is the gapped open — a loss worse than −1R, not a clean stop fill |

Cost models live in `execution/slippage.py` and are **shared with the paper
broker**, so simulated and paper results stay consistent.

## Stocks now, options later

The engine trades equities (long, with shorts supported by `Side`). The
`OrderIntent` / `MarketSimulator` seam is where option contracts, multipliers and
per-contract commissions slot in later without touching the event loop.

## Metrics

`BacktestResult` exposes the required metrics directly and the full
`PerformanceReport` (objective-first) underneath:

| Required metric | Access |
|---|---|
| Profit Factor | `result.profit_factor` |
| Expectancy | `result.expectancy_r` |
| Average Winner | `result.average_winner` |
| Average Loser | `result.average_loser` |
| Largest Winner | `result.largest_winner` |
| Maximum Drawdown | `result.max_drawdown` |
| Equity Curve | `result.equity_curve` (pandas Series) |
| Trend Capture % | `result.trend_capture_pct` |

## Usage

```python
from momentum.backtest import BacktestEngine, BacktestConfig, OrderIntent
from momentum.execution.slippage import PerShareCommission, BpsSlippage

class MyStrategy:
    def on_bar(self, ctx):
        hist = ctx.history("AAPL")            # only bars up to ctx.now
        if len(hist) < 50 or ctx.position("AAPL"):
            return []
        close = hist["close"]
        if close.iloc[-1] > close.iloc[-50:].max() * 0.999:   # 50-day breakout
            stop = float(close.iloc[-1]) * 0.90
            return [OrderIntent("AAPL", quantity=100, stop_price=stop)]
        return []

cfg = BacktestConfig(initial_cash=100_000,
                     commission=PerShareCommission(0.005, 1.0),
                     slippage=BpsSlippage(5))
result = BacktestEngine(cfg).run({"AAPL": bars}, MyStrategy())

print(result.performance.summary())
print("profit factor", result.profit_factor, "trend capture %", result.trend_capture_pct)
result.equity_curve.plot()
```

Orders are filled at the next open; protective stops (mandatory on entries)
are then enforced gap-aware each subsequent bar, with MFE/MAE tracked so the
analytics layer can report trend capture.

## Persisted run detail + tearsheet

The operator-console backtest (`api/actions.run_backtest`, the desktop **Run
backtest** button) persists more than the summary row:

- **`optimization_results.details`** carries the run's **equity curve**
  (downsampled to ≤ ~250 points) and **trade list** (symbol, entry/exit dates,
  P&L, R, holding days, exit reason). `GET
  /backtests/optimizations/{run_id}/detail` serves it; the desktop
  **Backtesting** view renders the equity curve (SVG) + trade table when a run
  is selected.
- **HTML tearsheet** — `momentum.reporting` (`plots.py` → `tearsheet.py` →
  `report_generator.py`) renders a self-contained Plotly document (equity,
  drawdown/underwater, R-distribution, rolling expectancy + headline metrics,
  stamped with run id & package version) to
  `<MRP_USER_DIR>/reports/tearsheet-<run_id>.html`; the path is returned in the
  job summary and the document is served by `GET
  /backtests/optimizations/{run_id}/tearsheet` — the Backtesting run detail has
  an **Open tearsheet** button that opens it in the system browser.
  Best-effort: a reporting failure never fails the backtest.

## Walk-forward (out-of-sample) testing

`momentum.backtest.walk_forward` answers the question a single full-sample
backtest cannot: **does the edge survive on data it wasn't fitted to?**

- **Expanding-window folds** — the shared bar history is cut into
  `n_folds + 1` equal segments; fold *k* trains on segments `[0..k)`
  (in-sample) and is evaluated on segment `k` (out-of-sample). Both sides run
  through the real event-driven `BacktestEngine` (same costs, same
  no-look-ahead guarantees), so OOS numbers are honest.
- **Pure** — `walk_forward(bars, strategy_factory, config=..., n_folds=3)`
  returns a `WalkForwardReport` (per-fold `FoldMetrics` for each side plus
  aggregate `is_expectancy_r` / `oos_expectancy_r` / `degradation` = OOS/IS).
  Raises on insufficient history (each slice needs ≥ 60 bars).
- **Persisted** — `api/actions.walk_forward_backtest`
  (`POST /actions/walk-forward`, the desktop **Walk-forward** button) persists
  one `optimization_results` row per fold+sample (`study_name="walk_forward"`,
  `sample` ∈ in_sample/out_of_sample, `fold` = k) under one run id; the
  Backtesting table shows the Sample (IS/OOS) and Fold columns.

## Benchmark overlay

Every persisted backtest detail also carries a **SPY buy-and-hold benchmark
curve** (`details["benchmark_curve"]`, same `{ts, equity}` schema, scaled to
the strategy's starting equity and restricted to the backtest window). The
Backtesting equity chart draws it as a dashed slate line, so "did this beat
just holding the index?" is answered at a glance. Best-effort: a missing SPY
series simply omits the overlay.
