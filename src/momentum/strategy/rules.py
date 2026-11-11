"""The momentum-breakout rules — pure functions, one definition used everywhere.

The strategy in one paragraph: when the market is in an uptrend (benchmark above
its 200-day average), buy stocks that are in the top fifth of the universe by
blended 3/6/12-month return, trade above their own 200-day average, and have
made a new 50-day high within the last 10 sessions. Risk a fixed small fraction
of the account per trade against a 3×ATR stop. Never sell into strength: hold
until a daily *close* below the prior 50-day low (or the stop). Losers are cut
at about 1R; winners are left to run.

Everything here is computed on **completed** daily bars — a session still in
progress is excluded by :func:`completed_bars` — because the rules were
validated on closes with next-session fills. The scanner, the trade plan, the
trade manager, Auto Pilot and the backtest all call these same functions, so
what is tested is exactly what is traded.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from momentum.signals.indicators import atr as wilder_atr
from momentum.strategy.config import StrategyConfig

_MARKET_TZ = ZoneInfo("America/New_York")
# A daily bar is treated as final a few minutes after the regular close.
_SESSION_FINAL = dt.time(16, 5)

FEATURE_COLUMNS = (
    "close",
    "trend_ma",
    "atr",
    "dollar_volume",
    "momentum",
    "breakout_level",
    "breakout",
    "bars_since_breakout",
    "exit_signal",
    "exit_level",
)


@dataclass(frozen=True, slots=True)
class SignalFeatures:
    """One symbol's strategy inputs as of its last completed bar."""

    as_of: pd.Timestamp
    close: float
    trend_ma: float | None
    atr: float | None
    dollar_volume: float | None
    momentum: float | None  # blended trailing return (fraction)
    breakout_level: float | None  # the prior N-day high in force on the last bar
    bars_since_breakout: int | None  # 0 = broke out on the last bar; None = none recently
    exit_signal: bool  # last close finished below the prior exit-lookback low
    exit_level: float | None  # the low the NEXT close must hold above

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "close": self.close,
            "trend_ma": self.trend_ma,
            "atr": self.atr,
            "dollar_volume": self.dollar_volume,
            "momentum": self.momentum,
            "breakout_level": self.breakout_level,
            "bars_since_breakout": self.bars_since_breakout,
            "exit_signal": self.exit_signal,
            "exit_level": self.exit_level,
        }


# --------------------------------------------------------------------------- #
# Bars
# --------------------------------------------------------------------------- #
def live_clock() -> dt.datetime | None:
    """The instant live callers read signals at (the one clock seam).

    Live code calls ``rules.live_clock()`` and passes the result as ``now`` to
    :func:`completed_bars` / :func:`signal_features`. Tests replace this
    function — returning ``None`` treats every bar as complete — so results
    never depend on the time of day the suite runs.
    """
    return dt.datetime.now(tz=dt.UTC)


def completed_bars(frame: pd.DataFrame, now: dt.datetime | None) -> pd.DataFrame:
    """``frame`` without a still-forming daily bar.

    Providers return today's partial bar while the session is open; signals must
    not react to it. The last bar is dropped when it is dated *today* (New York)
    and the regular session has not finished. ``now=None`` keeps every bar
    (historical data — the backtest).
    """
    if now is None or frame is None or frame.empty:
        return frame
    now_et = (now if now.tzinfo else now.replace(tzinfo=dt.UTC)).astimezone(_MARKET_TZ)
    if session_date(pd.Timestamp(frame.index[-1])) == now_et.date() and (
        now_et.time() < _SESSION_FINAL
    ):
        return frame.iloc[:-1]
    return frame


def market_date(instant: dt.datetime) -> dt.date:
    """The New York calendar date of an instant (naive values are read as UTC)."""
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=dt.UTC)
    return aware.astimezone(_MARKET_TZ).date()


def session_date(stamp: pd.Timestamp) -> dt.date:
    """The trading-session date a daily bar's timestamp stands for.

    Vendors stamp daily bars differently: at the session open (Yahoo, ~13:30
    UTC), at New York midnight (Alpaca/Polygon, 04:00–05:00 UTC) or as a bare
    date at 00:00 UTC. A midnight-UTC stamp is a date *label* (converting it to
    New York time would shift it to the previous day); anything else is an
    instant and is read in New York time.
    """
    if stamp.tzinfo is None:
        return _as_date(stamp)
    utc = stamp.tz_convert("UTC")
    if utc.time() == dt.time(0, 0):
        return _as_date(utc)
    return _as_date(stamp.tz_convert(_MARKET_TZ))


def _as_date(stamp: pd.Timestamp) -> dt.date:
    return dt.date(stamp.year, stamp.month, stamp.day)


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #
def feature_frame(frame: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Every strategy input for every bar of one symbol (vectorised, causal).

    Row ``t`` uses bars ``<= t`` only, so the frame can be computed once over a
    full history and read point-in-time by the backtest without look-ahead.
    """
    close = frame["close"].astype(float)
    high = frame["high"].astype(float) if "high" in frame.columns else close
    low = frame["low"].astype(float) if "low" in frame.columns else close
    volume = (
        frame["volume"].astype(float)
        if "volume" in frame.columns
        else pd.Series(0.0, index=frame.index)
    )

    out = pd.DataFrame(index=frame.index)
    out["close"] = close
    out["trend_ma"] = close.rolling(config.trend_ma_period).mean()
    out["atr"] = wilder_atr(high, low, close, config.atr_period)
    out["dollar_volume"] = (close * volume).rolling(20).mean()

    total_weight = sum(config.momentum_lookbacks.values())
    momentum = pd.Series(0.0, index=frame.index)
    for period, weight in config.momentum_lookbacks.items():
        momentum = momentum + (close / close.shift(period) - 1.0) * (weight / total_weight)
    out["momentum"] = momentum  # NaN until the longest lookback is available

    # Breakout: the close clears the highest high of the PRIOR N bars.
    prior_high = high.rolling(config.breakout_lookback).max().shift(1)
    breakout = close > prior_high
    out["breakout_level"] = prior_high
    out["breakout"] = breakout
    out["bars_since_breakout"] = _bars_since(breakout.to_numpy(dtype=bool))

    # Trend exit: the close finishes below the lowest low of the PRIOR M bars.
    prior_low = low.rolling(config.exit_lookback).min().shift(1)
    out["exit_signal"] = close < prior_low
    # The level tomorrow's close is judged against (includes today's low).
    out["exit_level"] = low.rolling(config.exit_lookback).min()
    return out


def _bars_since(flags: np.ndarray) -> np.ndarray:
    """Bars since the most recent ``True`` (0 on a ``True`` bar; NaN before any)."""
    idx = np.arange(len(flags), dtype=float)
    last_true = pd.Series(np.where(flags, idx, np.nan)).ffill().to_numpy(dtype=float)
    since: np.ndarray = idx - last_true
    return since


def signal_features(
    frame: pd.DataFrame | None, config: StrategyConfig, *, now: dt.datetime | None = None
) -> SignalFeatures | None:
    """The strategy inputs for one symbol as of its last completed bar."""
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    bars = completed_bars(frame, now)
    bars = bars[bars["close"].notna()]
    if bars.empty:
        return None
    # Only the tail matters for the latest row; bound the work on long histories.
    tail = bars.iloc[-(config.min_history + config.exit_lookback + 5) :]
    row = feature_frame(tail, config).iloc[-1]
    since = row["bars_since_breakout"]
    return SignalFeatures(
        as_of=pd.Timestamp(tail.index[-1]),
        close=float(row["close"]),
        trend_ma=_opt(row["trend_ma"]),
        atr=_opt(row["atr"]),
        dollar_volume=_opt(row["dollar_volume"]),
        momentum=_opt(row["momentum"]),
        breakout_level=_opt(row["breakout_level"]),
        bars_since_breakout=None if pd.isna(since) else int(since),
        exit_signal=bool(row["exit_signal"]),
        exit_level=_opt(row["exit_level"]),
    )


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #
def recent_breakout(bars_since_breakout: float | int | None, config: StrategyConfig) -> bool:
    """A new N-day high was made within the configured number of sessions."""
    if bars_since_breakout is None or (
        isinstance(bars_since_breakout, float) and math.isnan(bars_since_breakout)
    ):
        return False
    return bars_since_breakout < config.breakout_within


def market_uptrend(
    benchmark: pd.DataFrame | pd.Series | None,
    config: StrategyConfig,
    *,
    now: dt.datetime | None = None,
) -> bool | None:
    """Is the benchmark's last completed close above its regime moving average?

    ``None`` when there is not enough history to say (callers treat unknown as
    "do not open new positions").
    """
    if benchmark is None or len(benchmark) == 0:
        return None
    if isinstance(benchmark, pd.DataFrame):
        close = completed_bars(benchmark, now)["close"]
    else:
        close = benchmark
    close = close.dropna()
    if len(close) < config.regime_ma_period:
        return None
    return bool(close.iloc[-1] > close.iloc[-config.regime_ma_period :].mean())


def initial_stop(entry: float, atr: float, config: StrategyConfig) -> float:
    """The protective stop for a new long: ``entry − stop_atr_mult × ATR``."""
    return entry - config.stop_atr_mult * atr


def position_size(equity: float, entry: float, stop: float, config: StrategyConfig) -> int:
    """Shares to buy: risk-based, capped by the per-position limit.

    ``risk_per_trade_pct`` of equity is what is lost if the stop is hit; the
    position's dollar value never exceeds ``max_position_pct`` of equity.
    """
    risk_per_share = entry - stop
    if equity <= 0 or entry <= 0 or risk_per_share <= 0:
        return 0
    by_risk = config.risk_per_trade_pct * equity / risk_per_share
    by_cap = config.max_position_pct * equity / entry
    # The epsilon absorbs float noise (19.999999 shares is 20 shares).
    return max(0, math.floor(min(by_risk, by_cap) + 1e-9))


def _opt(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)
