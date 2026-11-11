"""Fast research backtester (vectorised indicators + daily portfolio loop).

No look-ahead: signals use data through the close of day t, fills happen at the
open of t+1; stops are gap-aware. Costs: slippage bps per side + per-share commission.
"""
from __future__ import annotations

import math
import pathlib
import pickle
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BARS = pathlib.Path(__file__).parent / "bars"
CACHE = pathlib.Path(__file__).parent / "panel.pkl"
INDEX = ("SPY", "QQQ", "IWM", "DIA")


def load_panel(start="2005-01-01"):
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    frames = {p.stem: pd.read_parquet(p) for p in sorted(BARS.glob("*.parquet"))}
    cal = frames["SPY"].index.normalize()
    cal = cal[cal >= pd.Timestamp(start, tz="UTC")]
    syms = [s for s in frames if s not in INDEX]
    out = {}
    for col in ("open", "high", "low", "close", "volume"):
        m = np.full((len(cal), len(syms)), np.nan)
        for j, s in enumerate(syms):
            f = frames[s]
            ser = pd.Series(f[col].to_numpy(dtype=float), index=f.index.normalize())
            ser = ser[~ser.index.duplicated(keep="last")]
            m[:, j] = ser.reindex(cal).to_numpy()
        out[col] = m
    spy = frames["SPY"]
    spy_c = pd.Series(spy["close"].to_numpy(float), index=spy.index.normalize()).reindex(cal)
    panel = {"cal": cal, "syms": syms, "spy": spy_c.to_numpy(), **out}
    CACHE.write_bytes(pickle.dumps(panel))
    return panel


def _roll(a, n, fn):
    return getattr(pd.DataFrame(a).rolling(n, min_periods=n), fn)().to_numpy()


def indicators(p):
    O, H, L, C, V = p["open"], p["high"], p["low"], p["close"], p["volume"]
    ind = {}
    for n in (20, 50, 100, 150, 200):
        ind[f"sma{n}"] = _roll(C, n, "mean")
    prevC = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    tr = np.nanmax(np.stack([H - L, np.abs(H - prevC), np.abs(L - prevC)]), axis=0)
    tr[np.isnan(C)] = np.nan
    ind["atr"] = _roll(tr, 20, "mean")
    sh = lambda a: np.vstack([np.full((1, a.shape[1]), np.nan), a[:-1]])  # noqa: E731
    for n in (20, 50, 100, 150, 252):
        ind[f"hh{n}"] = sh(_roll(H, n, "max"))  # prior N-day high (excl. today)
        ind[f"hc{n}"] = sh(_roll(C, n, "max"))  # prior N-day highest close
    for n in (10, 20, 50):
        ind[f"ll{n}"] = sh(_roll(L, n, "min"))
    ind["max252"] = _roll(C, 252, "max")
    for n in (63, 126, 252):
        ind[f"roc{n}"] = C / np.vstack([np.full((n, C.shape[1]), np.nan), C[:-n]]) - 1
    # 12-1 momentum
    c21 = np.vstack([np.full((21, C.shape[1]), np.nan), C[:-21]])
    c252 = np.vstack([np.full((252, C.shape[1]), np.nan), C[:-252]])
    ind["mom12_1"] = c21 / c252 - 1
    dv = C * V
    ind["dvol"] = _roll(dv, 20, "mean")
    ind["dvol50"] = _roll(dv, 50, "median")
    ind["rvol"] = V / sh(_roll(V, 50, "mean"))
    ind["sma200_up"] = ind["sma200"] > np.vstack(
        [np.full((20, C.shape[1]), np.nan), ind["sma200"][:-20]]
    )
    spy = pd.Series(p["spy"])
    ind["spy_sma200"] = spy.rolling(200).mean().to_numpy()
    ind["spy_sma50"] = spy.rolling(50).mean().to_numpy()
    ind["spy_vol20"] = (spy.pct_change().rolling(20).std() * np.sqrt(252)).to_numpy()
    for n in (100,):
        ind[f"ll{n}"] = sh(_roll(L, n, "min"))
    ind["blend"] = 0.4 * ind["roc63"] + 0.3 * ind["roc126"] + 0.3 * ind["roc252"]
    elig = (C >= 5) & (ind["dvol"] >= 20e6)
    for k in ("blend",):
        ind[k + "_erank"] = pd.DataFrame(np.where(elig, ind[k], np.nan)).rank(axis=1, pct=True).to_numpy()
    # cross-sectional rank of 6m momentum (0..1)
    for k in ("roc126", "roc252", "mom12_1", "blend"):
        ind[k + "_rank"] = pd.DataFrame(ind[k]).rank(axis=1, pct=True).to_numpy()
    # breadth: share of names above their 200dma
    above = (C > ind["sma200"]).astype(float)
    above[np.isnan(ind["sma200"])] = np.nan
    ind["breadth"] = np.nanmean(above, axis=1)
    return ind


@dataclass
class Params:
    name: str = "x"
    # universe
    min_price: float = 5.0
    min_dvol: float = 20e6
    # entry
    breakout: int = 50  # prior N-day high; 0 = none
    breakout_on: str = "hh"  # hh (highs) | hc (closes)
    breakout_within: int = 1  # breakout occurred within the last N bars
    vol_target: float = 0.0  # scale entry risk by min(1, vol_target / SPY 20d ann. vol)
    trend: str = "50>200"  # none | 50>200 | stage2
    min_rvol: float = 0.0
    near_high: float = 0.0  # require close >= (1-x)*252d max close ; 0 off
    rank_by: str = "roc126"
    min_rank_pct: float = 0.0  # cross-sectional momentum percentile floor
    regime: str = "spy200"  # none | spy200 | spy200+breadth
    max_ext_atr: float = 0.0  # skip if close > sma50 + x*ATR (overextended) ; 0 off
    max_gap_atr: float = 0.0  # skip entry if open gaps > x ATR above signal close
    # sizing
    risk_pct: float = 0.0075
    max_positions: int = 12
    max_pos_pct: float = 0.15
    # stop / exit
    stop_atr: float = 2.5
    trail_atr: float = 0.0  # chandelier from highest close; 0 off
    exit_ma: int = 0  # exit on close < smaN ; 0 off
    exit_ll: int = 0  # exit on close < prior N-day low ; 0 off
    trail_ll: int = 0  # intraday stop ratchets to the prior N-day low
    exit_rank: float = 0.0  # exit when momentum percentile falls below this ; 0 off
    time_stop: int = 0  # bars; exit if not at >= time_stop_r by then
    time_stop_r: float = 1.0
    targets: tuple = ()  # ((r_multiple, fraction), ...)
    breakeven_after_t1: bool = False
    regime_exit: bool = False  # liquidate when regime turns off
    # costs
    slip_bps: float = 5.0
    comm: float = 0.005
    start: str = "2006-01-03"
    end: str = "2099-01-01"
    cash0: float = 100_000.0


@dataclass
class Result:
    params: Params
    equity: pd.Series
    trades: list = field(default_factory=list)

    def stats(self, lo=None, hi=None):
        eq = self.equity
        if lo:
            eq = eq[eq.index >= pd.Timestamp(lo, tz="UTC")]
        if hi:
            eq = eq[eq.index < pd.Timestamp(hi, tz="UTC")]
        tr = [
            t
            for t in self.trades
            if (not lo or t["exit"] >= pd.Timestamp(lo, tz="UTC"))
            and (not hi or t["exit"] < pd.Timestamp(hi, tz="UTC"))
        ]
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
        dd = (eq / eq.cummax() - 1).min()
        rets = eq.pct_change().dropna()
        sharpe = rets.mean() / rets.std() * math.sqrt(252) if rets.std() > 0 else 0
        r = np.array([t["r"] for t in tr]) if tr else np.array([0.0])
        pnl = np.array([t["pnl"] for t in tr]) if tr else np.array([0.0])
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
        return {
            "cagr": cagr,
            "maxdd": dd,
            "mar": cagr / -dd if dd < 0 else 0,
            "sharpe": sharpe,
            "trades": len(tr),
            "win": float((r > 0).mean()),
            "exp_r": float(r.mean()),
            "pf": pf,
            "avg_win_r": float(r[r > 0].mean()) if (r > 0).any() else 0,
            "avg_loss_r": float(r[r <= 0].mean()) if (r <= 0).any() else 0,
            "max_r": float(r.max()),
            "hold": float(np.mean([t["bars"] for t in tr])) if tr else 0,
        }


def run(p, ind, P: Params, allow=None) -> Result:
    cal = p["cal"]
    O, H, L, C = p["open"], p["high"], p["low"], p["close"]
    T, N = C.shape
    atr = ind["atr"]
    t0 = int(np.searchsorted(cal, pd.Timestamp(P.start, tz="UTC")))
    t1 = int(np.searchsorted(cal, pd.Timestamp(P.end, tz="UTC")))
    slip = P.slip_bps / 1e4

    # ---- precompute entry-signal matrix (uses close of t) ---------------- #
    sig = (C >= P.min_price) & (ind["dvol"] >= P.min_dvol)
    if P.breakout:
        b = C > ind[f"{P.breakout_on}{P.breakout}"]
        if P.breakout_within > 1:
            b = pd.DataFrame(b.astype(float)).rolling(P.breakout_within, min_periods=1).max().to_numpy() > 0
        sig &= b
    if P.trend == "50>200":
        sig &= (C > ind["sma50"]) & (ind["sma50"] > ind["sma200"])
    elif P.trend == "stage2":
        sig &= (
            (C > ind["sma50"])
            & (ind["sma50"] > ind["sma150"])
            & (ind["sma150"] > ind["sma200"])
            & ind["sma200_up"]
        )
    elif P.trend == ">200":
        sig &= C > ind["sma200"]
    elif P.trend == ">100":
        sig &= C > ind["sma100"]
    elif P.trend == "ema_stack":
        sig &= (ind["sma20"] > ind["sma50"]) & (ind["sma50"] > ind["sma200"])
    if P.min_rvol:
        sig &= ind["rvol"] >= P.min_rvol
    if P.near_high:
        sig &= C >= (1 - P.near_high) * ind["max252"]
    if P.min_rank_pct:
        sig &= ind[P.rank_by + "_rank"] >= P.min_rank_pct
    if P.max_ext_atr:
        sig &= C <= ind["sma50"] + P.max_ext_atr * atr
    sig &= ~np.isnan(atr)
    if allow is not None:
        sig &= allow[None, :]
    rank = ind[P.rank_by]

    spy, s200 = p["spy"], ind["spy_sma200"]
    if P.regime == "none":
        reg = np.ones(T, bool)
    else:
        reg = spy > s200
        if P.regime == "spy200+breadth":
            reg &= ind["breadth"] > 0.5

    cash = P.cash0
    pos: dict[int, dict] = {}
    pend_in: list[tuple[int, float, float]] = []  # (idx, signal_close, atr)
    pend_out: set[int] = set()
    eq_pts = []
    expo = []
    trades = []
    equity = cash

    def close(i, price, t, reason, shares=None):
        nonlocal cash
        q = pos[i]
        sh = q["sh"] if shares is None else shares
        px = price * (1 - slip)
        cash += px * sh - P.comm * sh
        q["real"] += (px - q["entry"]) * sh - P.comm * sh
        q["sh"] -= sh
        if q["sh"] <= 0:
            pnl = q["real"] - q["comm_in"]
            trades.append(
                {
                    "sym": p["syms"][i],
                    "entry_t": cal[q["t"]],
                    "exit": cal[t],
                    "pnl": pnl,
                    "r": pnl / q["risk$"],
                    "ret": pnl / (q["entry"] * q["sh0"]),
                    "ti": q["t"], "te": t,
                    "bars": t - q["t"],
                    "reason": reason,
                }
            )
            del pos[i]

    for t in range(t0, min(t1, T)):
        # 1. signal exits decided yesterday -> today's open
        for i in list(pend_out):
            if i in pos and not np.isnan(O[t, i]):
                close(i, O[t, i], t, pos[i].get("why", "signal"))
        pend_out = {i for i in pend_out if i in pos}

        # 2. stops / targets for positions held into today
        for i in list(pos):
            if np.isnan(O[t, i]):
                continue
            q = pos[i]
            if O[t, i] <= q["stop"]:
                close(i, O[t, i], t, "stop_gap")
                continue
            if L[t, i] <= q["stop"]:
                close(i, q["stop"], t, "stop")
                continue
            for k, (rm, frac) in enumerate(P.targets):
                if k < q["tk"]:
                    continue
                tp = q["entry"] + rm * q["rps"]
                if H[t, i] >= tp:
                    px = max(tp, O[t, i])
                    last = k == len(P.targets) - 1
                    sh = q["sh"] if last else min(q["sh"], math.floor(q["sh0"] * frac))
                    q["tk"] = k + 1
                    if P.breakeven_after_t1:
                        q["stop"] = max(q["stop"], q["entry"])
                    if sh > 0:
                        close(i, px, t, f"target{k+1}", shares=sh)
                    if i not in pos:
                        break

        # 3. entries decided yesterday -> today's open
        for i, sc, a in pend_in:
            if i in pos or np.isnan(O[t, i]) or len(pos) >= P.max_positions:
                continue
            o = O[t, i]
            if P.max_gap_atr and o > sc + P.max_gap_atr * a:
                continue
            entry = o * (1 + slip)
            stop = entry - P.stop_atr * a
            rps = entry - stop
            if rps <= 0 or stop <= 0:
                continue
            rk = P.risk_pct
            if P.vol_target:
                v = ind["spy_vol20"][t - 1]
                if v == v and v > 0:
                    rk *= min(1.0, P.vol_target / v)
            sh = math.floor(rk * equity / rps)
            sh = min(sh, math.floor(P.max_pos_pct * equity / entry), math.floor(cash / entry))
            if sh <= 0:
                continue
            cash -= entry * sh + P.comm * sh
            pos[i] = {
                "sh": sh, "sh0": sh, "entry": entry, "stop": stop, "rps": rps,
                "risk$": rps * sh, "hi": entry, "t": t, "tk": 0, "real": 0.0,
                "comm_in": P.comm * sh,
            }
            if L[t, i] <= stop:  # same-bar stop
                close(i, stop, t, "stop")
        pend_in = []

        # 4. end-of-day: update trail, mark equity
        equity = cash
        for i, q in pos.items():
            c = C[t, i]
            if np.isnan(c):
                c = q.get("last", q["entry"])
            q["last"] = c
            q["hi"] = max(q["hi"], c)
            if P.trail_atr and not np.isnan(atr[t, i]):
                q["stop"] = max(q["stop"], q["hi"] - P.trail_atr * atr[t, i])
            if P.trail_ll and t + 1 < T:
                lv = ind[f"ll{P.trail_ll}"][t + 1, i]
                if lv == lv:
                    q["stop"] = max(q["stop"], lv)
            equity += c * q["sh"]
        eq_pts.append(equity)
        expo.append(1 - cash / equity)

        # 5. exit signals at the close
        for i, q in pos.items():
            c = C[t, i]
            if np.isnan(c):
                continue
            why = None
            if P.exit_ma and c < ind[f"sma{P.exit_ma}"][t, i]:
                why = f"ma{P.exit_ma}"
            elif P.exit_ll and c < ind[f"ll{P.exit_ll}"][t, i]:
                why = f"ll{P.exit_ll}"
            elif P.exit_rank and ind[P.rank_by + "_rank"][t, i] < P.exit_rank:
                why = "rank"
            elif (
                P.time_stop
                and t - q["t"] >= P.time_stop
                and q["tk"] == 0
                and c < q["entry"] + P.time_stop_r * q["rps"]
            ):
                why = "time"
            elif P.regime_exit and not reg[t]:
                why = "regime"
            if why:
                q["why"] = why
                pend_out.add(i)

        # 6. entry signals at the close
        if reg[t]:
            free = P.max_positions - len(pos) + len(pend_out)
            if free > 0:
                cand = np.flatnonzero(sig[t])
                cand = [i for i in cand if i not in pos]
                if cand:
                    cand.sort(key=lambda i: -(rank[t, i] if not np.isnan(rank[t, i]) else -9))
                    pend_in = [(i, C[t, i], atr[t, i]) for i in cand[:free]]

    eq = pd.Series(eq_pts, index=cal[t0 : t0 + len(eq_pts)])
    # liquidate open positions at last close for stats
    tl = t0 + len(eq_pts) - 1
    for i in list(pos):
        close(i, pos[i].get("last", pos[i]["entry"]), tl, "open")
    res = Result(P, eq, trades)
    res.expo = float(np.mean(expo))
    return res


def bench(p, ind, start="2006-01-03", allow=None):
    cal = p["cal"]
    t0 = int(np.searchsorted(cal, pd.Timestamp(start, tz="UTC")))
    spy = pd.Series(p["spy"][t0:], index=cal[t0:])
    C = p["close"]
    r = C[1:] / C[:-1] - 1
    elig = ~np.isnan(r) & (ind["dvol"][:-1] >= 20e6)
    if allow is not None:
        elig &= allow[None, :]
    rr = np.where(elig, r, np.nan)
    ew = np.nanmean(rr, axis=1)
    ew = pd.Series(np.concatenate([[0], ew]), index=cal).iloc[t0:]
    ew_eq = (1 + ew.fillna(0)).cumprod()
    return spy / spy.iloc[0], ew_eq / ew_eq.iloc[0]


def fmt(name, s):
    return (
        f"{name:34s} CAGR {s['cagr']*100:6.1f}%  DD {s['maxdd']*100:6.1f}%  MAR {s['mar']:.2f}  "
        f"Sh {s['sharpe']:.2f}  n {s['trades']:5d}  win {s['win']*100:4.0f}%  "
        f"E {s['exp_r']:+.2f}R  PF {s['pf']:.2f}  W {s['avg_win_r']:+.1f} L {s['avg_loss_r']:+.1f} "
        f"max {s['max_r']:.0f}R hold {s['hold']:.0f}"
    )
