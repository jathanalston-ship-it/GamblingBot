# The strategy — rules, evidence and limits

Momentum Lab trades **one** set of rules. They live in
`config/strategy.example.yaml` → `momentum.strategy.StrategyConfig`, and the
scanner, the trade plan, the trade manager, Auto Pilot and the backtester all
call the same pure functions in `momentum/strategy/rules.py`. What is tested is
exactly what is traded.

## The rules

| | Rule | Setting |
| --- | --- | --- |
| **Market gate** | Open new positions only while SPY's last completed close is above its 200-day average. | `regime_ma_period: 200` |
| **Tradeable** | Price above $5, 20-day average dollar volume ≥ $20M. | `min_price`, `min_dollar_volume` |
| **Leader** | Blended 3/6/12-month return (weights 0.4/0.3/0.3) in the top 20% of the scanned universe. | `min_momentum_rank: 0.80`, `momentum_lookbacks` |
| **Uptrend** | Close above the stock's own 200-day average. | `trend_ma_period: 200` |
| **Breakout** | A close above the prior 50-day high, within the last 10 sessions. | `breakout_lookback: 50`, `breakout_within: 10` |
| **Order** | Signals are taken strongest momentum first, at the next session's open. | scan rank |
| **Stop** | Entry − 3 × ATR(20). Honoured intraday. | `stop_atr_mult: 3.0`, `atr_period: 20` |
| **Exit** | A daily **close** below the prior 50-day low → sell. No profit target. | `exit_lookback: 50` |
| **Size** | Risk 0.5% of the account per trade; at most 8% of the account in one stock; at most 20 positions. | `risk_per_trade_pct`, `max_position_pct`, `max_positions` |

Signals are computed on **completed** daily bars only (`rules.completed_bars`
drops a still-forming session), so the list changes once a day, after the close,
exactly as backtested; `price` on screen is still the freshest print.

## Why these rules (what the data said)

Research universe: ~690 currently liquid US stocks, daily bars 2005–2026 (Yahoo,
split/dividend adjusted), 5 bps slippage per side + $0.005/share, signals at the
close and fills at the next open, gap-aware stops. Rules were chosen on
**2006–2017** and then checked on **2018–2026**, which they had never seen.
Scripts: `scripts/research/` (an independent harness — it and the app's own
engine cross-check each other).

### 1. The exit decides the outcome — the old exits destroyed the edge

Every 50-day-breakout signal in an uptrend, same entries, different exits
(expectancy per trade in R = multiples of the amount risked):

| Exit rule | 2006–2017 | 2018–2026 |
| --- | --- | --- |
| **Previous app logic** — sell thirds at +1R / +2R / +3.5R, breakeven stop, 10-day time stop | +0.04R, PF 1.08 | +0.01R, PF 1.02 |
| Close below the 50-day average | +0.27R, PF 1.52 | +0.16R, PF 1.29 |
| Close below the 100-day average | +0.54R, PF 1.90 | +0.32R, PF 1.49 |
| **Close below the 50-day low** (chosen) | +0.80R, PF 2.25 | +0.42R, PF 1.60 |

Selling winners at fixed targets caps the few large gains that pay for the many
small losses. That is why profit-target selling and the breakeven ratchet are now
**off by default** (`config/trade_lifecycle.example.yaml`).

### 2. Entries add timing discipline, not stock-picking skill

Measured against simply holding the same stocks over the same days, breakout
entries earn roughly **zero excess** (about −1 to −2%/yr in-sample, about
+0.5%/yr out-of-sample).
The breakout, relative-volume and sector filters do not select better stocks;
they define *when* a position is opened. Two things did hold up in both halves:

* **The market gate.** Without it the worst drawdown in 2006–2017 nearly doubles
  (about −43% vs −24%) for no extra return.
* **Momentum rank, conditional on the gate.** Among stocks above their 200-day
  average, bought only in an uptrend, the top fifth by blended momentum beat the
  bottom fifth in both halves (≈ +3.5%/yr and ≈ +8%/yr) — and the app's existing
  3/6/12-month blend was the strongest of the rankings tried.

Untested gates the app used to apply (relative volume ≥ 1, within 25% of the
all-time high, EMA stack, sector strength, a conviction floor, the committee
veto) are now off by default or advisory.

### 3. Robustness

Ten random half-universes, median [min, max]:

| | 2006–2017 CAGR | worst drawdown | 2018–2026 CAGR | worst drawdown |
| --- | --- | --- | --- | --- |
| **These rules** | 11.4% [8.6, 13.0] | −24% | 13.0% [11.5, 18.0] | −32% |
| Previous app logic | 2.4% [0.8, 7.1] | −59% | 14.2% [8.8, 19.4] | −34% |
| SPY buy & hold | 8.6% | −55% | 14.0% | −34% |

* Positive in every one of the 20 samples.
* Neighbouring settings (stop 2.5–4 ATR, 15–30 positions, rank floor 0.5–0.9,
  breakout 20–252 days, exit on 50-day low vs 100-day average) all land in the
  same range — a plateau, not a tuned peak.
* Tripling trading costs (15 bps per side) costs about 0.5–1%/yr.

### 4. The production implementation, on the production engine

`momentum.strategy.MomentumBreakoutStrategy` through `momentum.backtest.BacktestEngine`
(`scripts/research/production_backtest.py`), 2006–2026:

| Universe | CAGR | Max drawdown | Expectancy | Profit factor |
| --- | --- | --- | --- | --- |
| App default (96 large caps) | 10.6% | −21% | +0.79R | 2.14 |
| ~690-stock research universe | 13.1% | −34% | +0.71R | 2.20 |
| SPY buy & hold | 10.9% | −55% | | |

Default universe by year, strategy / SPY (%):

```
2006  +3/+16   2007 +16/ +5   2008 -17/-37   2009 +15/+26   2010 +10/+15   2011  -2/ +2
2012 +19/+16   2013 +47/+32   2014  +8/+13   2015  +8/ +1   2016 +10/+12   2017 +20/+22
2018  +9/ -5   2019 +16/+31   2020 +20/+18   2021 +16/+29   2022 -13/-18   2023 +19/+26
2024 +30/+25   2025  +3/+18
```

Three losing years in twenty (2008, 2011, 2022). The in-app test (**Results →
Run the 20-year test**) runs this same code on your selected universe.

## What to expect — honestly

* **About the market's long-run return, with roughly half the worst drawdown.**
  That is the realistic claim. It is not a way to double the index.
* **It lags in strong, steady bull markets** (2019, 2021, 2025) and earns its
  keep in bear markets (2008, 2022) by standing aside.
* **About two trades in three lose** (≈ −0.9R each). Winners average ≈ +3.5R and
  are held for months. The top tenth of trades produce more than all of the net
  profit, so skipping signals — or selling winners early — breaks the result.
  This is what Auto Pilot is for.
* **Weeks with nothing to do are normal**, and so are runs of small losses.

## Limits of the evidence

* **Survivorship bias.** The tests use *today's* stock lists; companies that
  failed or were acquired are missing. This flatters every number above, most of
  all the widest universe. Expect less in live trading.
* **One market, one era.** US large/mid caps, 2006–2026, long only.
* **Data.** Yahoo daily bars, dividend-adjusted; no intraday path within a bar
  (a stop and a gap on the same day are resolved conservatively).
* **No guarantee.** A positive backtest is evidence, not a promise. The app is
  paper-only; nothing here is investment advice.

## Changing the rules

Edit `<user dir>/config/strategy.yaml` (bootstrapped from the shipped example).
Every consumer picks the change up, and **Results → Run again** re-tests the new
rules (the evidence card flags a backtest that no longer matches the live
rules). A shipped example whose `model_version` changes supersedes an older
bootstrapped user file (kept as `*.yaml.bak`) — see `core/config_paths.py`.
