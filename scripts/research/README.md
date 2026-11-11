# Strategy research scripts

The evidence behind `config/strategy.example.yaml` (see `docs/STRATEGY.md`).
These are research tools, not part of the app: they are not imported by the
package and are not covered by the lint/type gate.

```bash
# 1. Download ~20 years of daily bars (Yahoo; ~700 symbols, a few minutes).
mkdir -p scripts/research/bars
PYTHONPATH=src python scripts/research/download_bars.py scripts/research/bars scripts/research/universe_wide.txt
printf 'SPY\nQQQ\nIWM\nDIA\n' > /tmp/idx.txt
PYTHONPATH=src python scripts/research/download_bars.py scripts/research/bars /tmp/idx.txt

# 2. The experiments (run from scripts/research/).
cd scripts/research
python entry_vs_exit.py        # entries barely matter; exits decide the outcome
python factor_quintiles.py     # which momentum ranking separates winners
python monte_carlo.py 10       # rule sets on 10 random half-universes, IS vs OOS

# 3. The production implementation on the production engine (from the repo root).
PYTHONPATH=src python scripts/research/production_backtest.py
```

| File | What it is |
| --- | --- |
| `harness.py` | A fast, independent research backtester (vectorised indicators + a daily portfolio loop; next-open fills, gap-aware stops, costs). Deliberately separate from the app's engine so the two can check each other. |
| `entry_vs_exit.py` | Every-signal expectancy by entry rule × exit rule, vs holding the same stocks. |
| `factor_quintiles.py` | Monthly quintile returns for candidate rankings, with/without the market gate. |
| `monte_carlo.py` | Random half-universe robustness, in-sample vs out-of-sample. |
| `production_backtest.py` | `momentum.strategy.MomentumBreakoutStrategy` on `momentum.backtest.BacktestEngine`. |
| `universe_wide.txt` | The ~700-symbol research universe (current liquid US stocks). |

`bars/` and `*.pkl` are local data caches and are git-ignored.
