"""Download max daily history for the research universe into parquet (one per symbol)."""
import sys, time, yaml, pathlib, concurrent.futures as cf
import pandas as pd
from momentum.data.providers.yfinance import YahooProvider
out = pathlib.Path(sys.argv[1]); syms_file = sys.argv[2]
syms = [s.strip().upper() for s in open(syms_file).read().split() if s.strip()]
def one(sym):
    p = out / f"{sym}.parquet"
    if p.exists(): return sym, "cached"
    prov = YahooProvider()
    for attempt in range(3):
        try:
            df = prov.get_bars(sym, "2004-01-01", pd.Timestamp.now(tz="UTC"))
            if len(df) < 300: return sym, f"short {len(df)}"
            df.to_parquet(p); return sym, len(df)
        except Exception as e:
            err = str(e)[:80]; time.sleep(1.5 * (attempt + 1))
    return sym, "ERR " + err
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, syms))
bad = [r for r in res if isinstance(r[1], str) and r[1] != "cached"]
print(len(res), "requested;", len(bad), "failed:", bad[:40])
