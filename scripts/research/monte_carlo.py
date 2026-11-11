"""Robustness: run a rule set on K random half-universes and report the spread,
in-sample (2006-2017) and out-of-sample (2018+). A rule that only works on one
lucky set of stocks shows up here as a wide spread.
"""
import warnings; warnings.filterwarnings("ignore")
import sys
from dataclasses import replace
from harness import *
p=load_panel(); ind=indicators(p); N=p["close"].shape[1]
K=int(sys.argv[1]) if len(sys.argv)>1 else 10
rng=np.random.default_rng(7); masks=[rng.random(N)<0.5 for _ in range(K)]
PER=(("IS","2006-01-03","2018-01-01"),("OOS","2018-01-01","2099-01-01"))
def bs(eq,a,b):
    eq=eq[(eq.index>=pd.Timestamp(a,tz="UTC"))&(eq.index<pd.Timestamp(b,tz="UTC"))]
    yrs=(eq.index[-1]-eq.index[0]).days/365.25; return (eq.iloc[-1]/eq.iloc[0])**(1/yrs)-1, (eq/eq.cummax()-1).min()
ewb=[bench(p,ind,allow=m)[1] for m in masks]
spy=bench(p,ind)[0]
print("SPY: "+"  ".join(f"{l} {bs(spy,a,b)[0]*100:.1f}%/{bs(spy,a,b)[1]*100:.0f}%" for l,a,b in PER))
print("EW half-universes (median): "+"  ".join(f"{l} {np.median([bs(e,a,b)[0] for e in ewb])*100:.1f}%/{np.median([bs(e,a,b)[1] for e in ewb])*100:.0f}%" for l,a,b in PER))
def mc(tag, **kw):
    P=Params(name=tag, **kw); rs=[run(p,ind,P,allow=m) for m in masks]
    out=f"{tag:38s}"
    for l,a,b in PER:
        st=[r.stats(a,b) for r in rs]; c=np.array([s['cagr'] for s in st])*100; d=np.array([s['maxdd'] for s in st])*100
        al=c-np.array([bs(e,a,b)[0] for e in ewb])*100
        out+=f" | {l} CAGR med {np.median(c):5.1f} [{c.min():5.1f},{c.max():5.1f}] DD med {np.median(d):5.1f} worst {d.min():5.1f} vsEW {np.median(al):+5.1f} E {np.median([s['exp_r'] for s in st]):+.2f}R PF {np.median([s['pf'] for s in st]):.2f}"
    out+=f" | expo {np.mean([r.expo for r in rs])*100:.0f}%"
    print(out, flush=True)
if __name__=="__main__":
    Z=dict(rank_by="blend", max_positions=20, risk_pct=0.005, max_pos_pct=0.08, stop_atr=3.0)
    mc("M1 nobrk rank.8 <100", breakout=0, trend=">200", min_rank_pct=0.8, exit_ma=100, **Z)
    mc("M2 brk50 rank.8 <100", breakout=50, trend=">200", min_rank_pct=0.8, exit_ma=100, **Z)
    mc("M3 brk50 rank0 <100", breakout=50, trend=">200", exit_ma=100, **Z)
    mc("M4 brk20 rank.8 <100", breakout=20, trend=">200", min_rank_pct=0.8, exit_ma=100, **Z)
    mc("M5 nobrk rank.8 ll50", breakout=0, trend=">200", min_rank_pct=0.8, exit_ll=50, **Z)
    mc("M6 nobrk rank.8 <50", breakout=0, trend=">200", min_rank_pct=0.8, exit_ma=50, **Z)
    mc("M7 nobrk rank.8 <100 +rank<.5", breakout=0, trend=">200", min_rank_pct=0.8, exit_ma=100, exit_rank=0.5, **Z)
    mc("M8 nobrk rank.6 <100", breakout=0, trend=">200", min_rank_pct=0.6, exit_ma=100, **Z)
    mc("M9 brk252 rank.8 <100", breakout=252, trend=">200", min_rank_pct=0.8, exit_ma=100, **Z)
    mc("CURRENT app", breakout=0, trend="ema_stack", min_rvol=1.0, near_high=0.25, rank_by="roc126", stop_atr=1.8, targets=((1.0,.34),(2.0,.33),(3.5,.33)), breakeven_after_t1=True, time_stop=10, regime="none", risk_pct=0.01, max_positions=10)
