"""Run the PRODUCTION strategy (momentum.strategy) on the PRODUCTION backtest engine
over the downloaded research bars, for three universes, split by period.

    PYTHONPATH=src python scripts/research/production_backtest.py
"""
import sys, pathlib, warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, yaml
from momentum.backtest import BacktestEngine, BacktestConfig
from momentum.strategy import MomentumBreakoutStrategy, StrategyConfig
from momentum.universe.membership import select_universe
BARS=pathlib.Path(__file__).parent/"bars"
allf={p.stem: pd.read_parquet(p) for p in sorted(BARS.glob("*.parquet"))}
spy=allf["SPY"]
d=yaml.safe_load(open('config/universes.example.yaml'))['universes']
default,_=select_universe()
sets={"default96":set(default), "shipped-all216":set(d['all']['symbols'] if isinstance(d['all'],dict) else d['all']), "research691":set(allf)-{"SPY","QQQ","IWM","DIA"}}
def stats(eq,a,b):
    e=eq[(eq.index>=pd.Timestamp(a,tz="UTC"))&(eq.index<pd.Timestamp(b,tz="UTC"))]; y=(e.index[-1]-e.index[0]).days/365.25
    return (e.iloc[-1]/e.iloc[0])**(1/y)-1, (e/e.cummax()-1).min()
sp=spy["close"]
for name,syms in sets.items():
    fr={s:allf[s] for s in syms if s in allf and len(allf[s])>300}
    res=BacktestEngine(BacktestConfig()).run(fr, MomentumBreakoutStrategy(fr, benchmark=spy))
    out=f"{name:16s} n={len(fr):3d} trades {len(res.trades):4d} E {res.expectancy_r:+.2f}R PF {res.profit_factor:.2f}"
    for lab,a,b in (("06-17","2006-01-03","2018-01-01"),("18-26","2018-01-01","2099-01-01"),("ALL","2006-01-03","2099-01-01")):
        c,dd=stats(res.equity_curve,a,b); sc,sd=stats(sp,a,b); out+=f" | {lab}: {c*100:5.1f}%/{dd*100:5.1f}%  (SPY {sc*100:.1f}%/{sd*100:.0f}%)"
    print(out, flush=True)
