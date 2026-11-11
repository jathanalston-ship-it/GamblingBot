"""Do the ENTRY rules or the EXIT rules carry the edge? Every-signal expectancy for
random / trend-only / breakout entries crossed with five exit styles (incl. the
app's former profit-target exits), measured against holding the same universe.
"""
import warnings; warnings.filterwarnings("ignore")
from dataclasses import replace
from harness import *
p=load_panel(); ind=indicators(p)
spy, ew = bench(p, ind, start="2005-01-03")
cal=p["cal"]; ewf=ew.reindex(cal).ffill().to_numpy(); spf=p["spy"]
def excess(r):
    tr=r.trades
    ret=np.array([t["ret"] for t in tr]); b=np.array([ewf[t["te"]]/ewf[t["ti"]]-1 for t in tr]); sp=np.array([spf[t["te"]]/spf[t["ti"]]-1 for t in tr])
    d=np.array([max(t["bars"],1) for t in tr])
    return ret.mean()*100, (ret-b).mean()*100, (ret-sp).mean()*100, ((ret-b).sum()/d.sum())*100*252, d.mean()
def show(tag, P):
    r=run(p,ind,P); s=r.stats(); e=excess(r)
    print(f"{tag:36s} n {s['trades']:6d} E {s['exp_r']:+.3f}R PF {s['pf']:.2f} | avg ret {e[0]:+.2f}%  vs EW-univ {e[1]:+.2f}%  vs SPY {e[2]:+.2f}%  excess/yr-held {e[3]:+.1f}%  hold {e[4]:.0f}")
for per,(a,b) in {"IS 2006-2017":("2006-01-03","2018-01-01"),"OOS 2018-2026":("2018-01-01","2099-01-01")}.items():
    U=dict(max_positions=100000, max_pos_pct=1.0, cash0=1e13, risk_pct=1e-7, start=a, end=b)
    print("==",per,"== all signals; excess = trade return minus equal-weight-universe return over same days")
    for ex,ekw in (("<50dma",dict(exit_ma=50)),("<100dma",dict(exit_ma=100)),("ll50",dict(exit_ll=50)),("trail5",dict(trail_atr=5.0)),("CURRENT",dict(targets=((1.0,.34),(2.0,.33),(3.5,.33)),breakeven_after_t1=True,time_stop=10,stop_atr=1.8))):
        show(f"RANDOM entry (any day) / {ex}", Params(breakout=0,trend="none",regime="none",**ekw,**U))
        show(f"trend only 50>200+regime / {ex}", Params(breakout=0,trend="50>200",**ekw,**U))
        show(f"50d breakout+trend+regime / {ex}", Params(breakout=50,trend="50>200",**ekw,**U))
        show(f"252d brk+trend+regime / {ex}", Params(breakout=252,trend="50>200",**ekw,**U))
        show(f"50d brk+rvol2+trend+regime / {ex}", Params(breakout=50,trend="50>200",min_rvol=2.0,**ekw,**U))
        show(f"50d brk top20% mom / {ex}", Params(breakout=50,trend="50>200",min_rank_pct=0.8,**ekw,**U))
