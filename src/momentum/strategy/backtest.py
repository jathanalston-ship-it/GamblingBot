"""The strategy as a :class:`~momentum.backtest.Strategy` — what is tested is what is traded.

:class:`MomentumBreakoutStrategy` plugs into the event-driven
:class:`~momentum.backtest.BacktestEngine`. It makes exactly the decisions the
live app makes, with the same pure functions (:mod:`momentum.strategy.rules`):

* **entries** — at each close, symbols passing every entry rule are ranked by
  blended momentum and bought at the next open while the market gate is open and
  the book has room; sized by :func:`~momentum.strategy.rules.position_size`
  with the stop ``stop_atr_mult × ATR`` below the actual fill;
* **exits** — the engine honours the protective stop intraday (gap-aware); a
  close below the prior ``exit_lookback``-day low sells at the next open.

All per-symbol features are precomputed once with causal rolling windows, then
read point-in-time by timestamp — fast, and free of look-ahead (proven by the
truncation test in ``tests/unit/strategy``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from momentum.backtest.engine import OrderIntent, StrategyContext
from momentum.strategy.config import StrategyConfig
from momentum.strategy.rules import feature_frame, position_size

ENTRY_TAG = "breakout"
EXIT_TAG = "trend_exit"


class MomentumBreakoutStrategy:
    """The production momentum-breakout rules, backtestable."""

    def __init__(
        self,
        bars: Mapping[str, pd.DataFrame],
        *,
        benchmark: pd.DataFrame | pd.Series | None = None,
        config: StrategyConfig | None = None,
        cash_buffer: float = 0.02,
    ) -> None:
        self.config = config or StrategyConfig()
        self.cash_buffer = cash_buffer
        cfg = self.config

        features = {
            symbol.upper(): feature_frame(frame, cfg)
            for symbol, frame in bars.items()
            if frame is not None and len(frame) > 0
        }
        self.symbols = sorted(features)

        def panel(column: str) -> pd.DataFrame:
            return pd.DataFrame({s: f[column] for s, f in features.items()})

        close = panel("close")
        momentum = panel("momentum")
        self._close = close
        self._atr = panel("atr")
        self._momentum = momentum
        rank = momentum.rank(axis=1, pct=True)
        entry = (
            (close > cfg.min_price)
            & (panel("dollar_volume") >= cfg.min_dollar_volume)
            & (close > panel("trend_ma"))
            & (rank >= cfg.min_momentum_rank)
            & (panel("bars_since_breakout") < cfg.breakout_within)
            & self._atr.notna()
        )
        self._entry = entry.fillna(False).astype(bool)
        self._exit = panel("exit_signal").fillna(False).astype(bool)
        self._market_ok = self._market_gate(benchmark, close.index)

    def _market_gate(
        self, benchmark: pd.DataFrame | pd.Series | None, index: pd.Index
    ) -> pd.Series:
        """Per-date market gate; with no benchmark the gate is always open."""
        if benchmark is None or len(benchmark) == 0:
            return pd.Series(True, index=index)
        series = benchmark["close"] if isinstance(benchmark, pd.DataFrame) else benchmark
        series = series.astype(float)
        ok = series > series.rolling(self.config.regime_ma_period).mean()
        # A date the benchmark did not trade inherits the last known state.
        return ok.reindex(index.union(ok.index)).ffill().reindex(index).fillna(False).astype(bool)

    # -- Strategy protocol -------------------------------------------------- #
    def on_bar(self, ctx: StrategyContext) -> Sequence[OrderIntent]:
        now = ctx.now
        if now not in self._close.index:
            return []
        cfg = self.config
        intents: list[OrderIntent] = []

        held = [s for s in self.symbols if ctx.position(s) is not None]
        exit_row = self._exit.loc[now]
        exiting = {s for s in held if bool(exit_row[s])}
        intents.extend(OrderIntent(s, 0, kind="exit", tag=EXIT_TAG) for s in sorted(exiting))

        if not bool(self._market_ok.loc[now]):
            return intents
        slots = cfg.max_positions - (len(held) - len(exiting))
        if slots <= 0:
            return intents

        entry_row = self._entry.loc[now]
        candidates = [s for s in self.symbols if bool(entry_row[s]) and s not in held]
        if not candidates:
            return intents
        momentum = self._momentum.loc[now]
        candidates.sort(key=lambda s: (-float(momentum[s]), s))

        equity = ctx.equity
        cash = ctx.cash * (1.0 - self.cash_buffer)
        closes = self._close.loc[now]
        atrs = self._atr.loc[now]
        for symbol in candidates[:slots]:
            price = float(closes[symbol])
            stop_distance = cfg.stop_atr_mult * float(atrs[symbol])
            shares = position_size(equity, price, price - stop_distance, cfg)
            shares = min(shares, int(cash // price)) if price > 0 else 0
            if shares <= 0:
                continue
            cash -= shares * price
            intents.append(OrderIntent(symbol, shares, stop_distance=stop_distance, tag=ENTRY_TAG))
        return intents
