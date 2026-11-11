"""Monthly quintile portfolios by momentum-style signals, with and without the
market gate — which ranking (if any) separates winners from losers?
"""
import warnings; warnings.filterwarnings("ignore")
from harness import *
p=load_panel(); ind=indicators(p); C=p["close"]; cal=p["cal"]
# month-end indices
me=[i for i in range(len(cal)-1) if cal[i].month!=cal[i+1].month and cal[i]>=pd.Timestamp("2005-12-30",tz="UTC")]
elig=(C>=5)&(ind["dvol"]>=20e6)
atrp=ind["atr"]/C
sigs={
 "roc126":ind["roc126"], "mom12_1":ind["mom12_1"], "roc252":ind["roc252"], "roc63":ind["roc63"],
 "near52wHi":C/ind["max252"], "voladj_mom126":ind["roc126"]/atrp, "voladj_mom12_1":ind["mom12_1"]/atrp,
 "blend(63,126,252)":0.4*ind["roc63"]+0.3*ind["roc126"]+0.3*ind["roc252"],
 "dist_above_sma200":C/ind["sma200"]-1,
}
reg=(p["spy"]>ind["spy_sma200"])
def q(sig, only_reg=False, trendf=False):
    rows=[]
    for a,b in zip(me[:-1],me[1:]):
        if only_reg and not reg[a]: rows.append([0]*5+[cal[b]]); continue
        ok=elig[a]&~np.isnan(sig[a])&~np.isnan(C[a])&~np.isnan(C[b])
        if trendf: ok&=C[a]>ind["sma200"][a]
        idx=np.flatnonzero(ok)
        if len(idx)<50: continue
        r=C[b,idx]/C[a,idx]-1; s=sig[a,idx]; order=np.argsort(s); k=len(idx)//5
        rows.append([r[order[i*k:(i+1)*k]].mean() for i in range(4)]+[r[order[4*k:]].mean(), cal[b]])
    df=pd.DataFrame(rows,columns=["Q1","Q2","Q3","Q4","Q5","d"]).set_index("d")
    return df
def ann(x): return ((1+x).prod()**(12/len(x))-1)*100
def dd(x): e=(1+x).cumprod(); return (e/e.cummax()-1).min()*100
print("Quintile portfolios (monthly, EW, no costs). Q5 = strongest signal. CAGR% [maxDD%]")
for name,sg in sigs.items():
    df=q(sg)
    for lab,sl in (("2006-17",slice("2006","2017")),("2018-26",slice("2018","2026"))):
        d=df.loc[sl]
        print(f"{name:22s} {lab}  "+"  ".join(f"Q{i+1} {ann(d[f'Q{i+1}']):5.1f}[{dd(d[f'Q{i+1}']):4.0f}]" for i in range(5))+f"   Q5-Q1 {ann(d['Q5'])-ann(d['Q1']):+5.1f}")
print("\nWith regime filter (cash when SPY<200dma at month-end) and stock>200dma:")
for name in ("roc126","mom12_1","near52wHi","voladj_mom126","blend(63,126,252)"):
    df=q(sigs[name],only_reg=True,trendf=True)
    for lab,sl in (("2006-17",slice("2006","2017")),("2018-26",slice("2018","2026"))):
        d=df.loc[sl]
        print(f"{name:22s} {lab}  "+"  ".join(f"Q{i+1} {ann(d[f'Q{i+1}']):5.1f}[{dd(d[f'Q{i+1}']):4.0f}]" for i in range(5))+f"   Q5-Q1 {ann(d['Q5'])-ann(d['Q1']):+5.1f}")
