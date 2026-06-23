"""Event-driven backtest engine with strict no-look-ahead discipline.

The loop, per bar ``t`` (in chronological order across all symbols):

1. **Resolve stops** for positions held *into* ``t`` — gap-aware (overnight gaps
   and intraday moves happen before you can react).
2. **Execute** orders decided on bar ``t-1`` at bar ``t``'s **open**.
3. Resolve same-bar intraday stops for just-opened positions.
4. Update MFE/MAE (and optional trailing stops) from the bar's range.
5. **Mark equity** at the bar's close.
6. Ask the strategy for orders, showing it history **only up to ``t``** — those
   orders are queued for ``t+1``.

The one-bar delay between decision and fill, plus a strategy view that is
physically truncated at the current bar, are the two guarantees against
look-ahead bias (proven in ``tests/unit/backtest``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from momentum.analytics import PerformanceReport, Trade, analyze_performance
from momentum.core.clock import SimulatedClock
from momentum.core.constants import TRADING_DAYS_PER_YEAR
from momentum.core.enums import Side
from momentum.execution.slippage import (
    BpsSlippage,
    CommissionModel,
    PerShareCommission,
    SlippageModel,
)
from momentum.backtest.market_sim import MarketSimulator


# --------------------------------------------------------------------------- #
# Strategy interface
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class OrderIntent:
    """An order a strategy wants placed; filled at the *next* bar's open."""

    symbol: str
    quantity: int  # shares (entry size); ignored for exits (closes the position)
    kind: str = "entry"  # "entry" | "exit"
    side: Side = Side.LONG
    stop_price: float | None = None  # protective stop for entries
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class PositionView:
    """Read-only snapshot of an open position handed to the strategy."""

    symbol: str
    side: Side
    shares: float
    entry_price: float
    stop_price: float
    bars_held: int


class StrategyContext(Protocol):
    """The *only* market view a strategy gets — never extends past ``now``."""

    @property
    def now(self) -> pd.Timestamp: ...
    def history(self, symbol: str) -> pd.DataFrame: ...
    def price(self, symbol: str) -> float | None: ...
    def position(self, symbol: str) -> PositionView | None: ...
    @property
    def equity(self) -> float: ...
    @property
    def cash(self) -> float: ...


class Strategy(Protocol):
    """Emits orders from a point-in-time context. No sizing/risk knowledge needed."""

    def on_bar(self, ctx: StrategyContext) -> Sequence[OrderIntent]: ...


# --------------------------------------------------------------------------- #
# Config & results
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Backtest cost & accounting assumptions."""

    initial_cash: float = 100_000.0
    commission: CommissionModel = field(default_factory=PerShareCommission)
    slippage: SlippageModel = field(default_factory=lambda: BpsSlippage(5.0))
    stop_slippage: SlippageModel | None = None
    allow_gap_fills: bool = True  # model gap risk on stops (recommended)
    periods_per_year: int = TRADING_DAYS_PER_YEAR


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Equity curve, closed trades and the objective-first performance report."""

    equity_curve: pd.Series
    trades: list[Trade]
    performance: PerformanceReport

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) else 0.0

    # convenience pass-throughs of the required headline metrics
    @property
    def profit_factor(self) -> float:
        return self.performance.trades.profit_factor

    @property
    def expectancy_r(self) -> float:
        return self.performance.trades.expectancy_r

    @property
    def average_winner(self) -> float:
        return self.performance.trades.avg_winner_dollars

    @property
    def average_loser(self) -> float:
        return self.performance.trades.avg_loser_dollars

    @property
    def largest_winner(self) -> float:
        return self.performance.trades.largest_winner_dollars

    @property
    def max_drawdown(self) -> float:
        return self.performance.max_drawdown

    @property
    def trend_capture_pct(self) -> float | None:
        tc = self.performance.trades.trend_capture
        return None if tc is None else 100.0 * tc


# --------------------------------------------------------------------------- #
# Internal position bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class _Position:
    symbol: str
    side: Side
    shares: float
    entry_price: float
    entry_time: pd.Timestamp
    stop_price: float
    risk_per_share: float
    entry_commission: float
    highest: float
    lowest: float
    bars_held: int = 0


class _SymbolData:
    """Per-symbol OHLCV as numpy arrays plus a timestamp -> row-index map."""

    __slots__ = ("frame", "index", "open", "high", "low", "close", "pos")

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.index = frame.index
        self.open = frame["open"].to_numpy(dtype=float)
        self.high = frame["high"].to_numpy(dtype=float)
        self.low = frame["low"].to_numpy(dtype=float)
        self.close = frame["close"].to_numpy(dtype=float)
        self.pos: dict[pd.Timestamp, int] = {ts: i for i, ts in enumerate(self.index)}

    def row(self, ts: pd.Timestamp) -> int | None:
        return self.pos.get(ts)

    def upto(self, ts: pd.Timestamp) -> pd.DataFrame:
        """Bars at or before ``ts`` — the truncated, no-future view."""
        count = int(self.index.searchsorted(ts, side="right"))
        return self.frame.iloc[:count]


class _Context:
    """Concrete StrategyContext bound to the engine's live state at one bar."""

    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    @property
    def now(self) -> pd.Timestamp:
        return self._engine.clock.now()

    def history(self, symbol: str) -> pd.DataFrame:
        data = self._engine.data.get(symbol.upper())
        if data is None:
            return pd.DataFrame()
        return data.upto(self.now)

    def price(self, symbol: str) -> float | None:
        hist = self.history(symbol)
        if hist.empty:
            return None
        return float(hist["close"].iloc[-1])

    def position(self, symbol: str) -> PositionView | None:
        pos = self._engine.positions.get(symbol.upper())
        if pos is None:
            return None
        return PositionView(
            symbol=pos.symbol,
            side=pos.side,
            shares=pos.shares,
            entry_price=pos.entry_price,
            stop_price=pos.stop_price,
            bars_held=pos.bars_held,
        )

    @property
    def equity(self) -> float:
        return self._engine.mark_to_market(self.now)

    @property
    def cash(self) -> float:
        return self._engine.cash


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class BacktestEngine:
    """Drives a strategy over historical bars with no look-ahead."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.sim = MarketSimulator(
            self.config.commission, self.config.slippage, self.config.stop_slippage
        )
        self.clock = SimulatedClock()
        self.cash = self.config.initial_cash
        self.data: dict[str, _SymbolData] = {}
        self.positions: dict[str, _Position] = {}
        self._closed: list[Trade] = []

    def run(
        self,
        bars: Mapping[str, pd.DataFrame],
        strategy: Strategy,
    ) -> BacktestResult:
        """Backtest ``strategy`` over ``bars`` (symbol -> canonical OHLCV)."""
        self.cash = self.config.initial_cash
        self.positions = {}
        self._closed = []
        self.data = {s.upper(): _SymbolData(f) for s, f in bars.items()}

        timeline = self._timeline()
        pending: list[OrderIntent] = []
        equity_points: list[float] = []
        ctx = _Context(self)

        for ts in timeline:
            self.clock.set_time(ts)

            # 1. stops for positions held INTO this bar (gap-aware)
            self._resolve_overnight_stops(ts, just_opened=set())

            # 2. execute orders decided on the previous bar, at this bar's open
            opened = self._execute(pending, ts)
            pending = []

            # 3. same-bar intraday stop for freshly opened positions (no open gap)
            self._resolve_overnight_stops(ts, just_opened=opened, intraday_only=True)

            # 4. update excursions / bars held for survivors
            self._update_positions(ts)

            # 5. mark equity at the close
            equity_points.append(self.mark_to_market(ts))

            # 6. strategy decides using history <= ts; queue for next bar
            pending = list(strategy.on_bar(ctx))

        # liquidate anything still open at the final close (for clean accounting)
        if timeline:
            self._liquidate(timeline[-1])

        equity_curve = pd.Series(equity_points, index=pd.DatetimeIndex(timeline), name="equity")
        report = analyze_performance(
            equity_curve, self._closed, periods_per_year=self.config.periods_per_year
        )
        return BacktestResult(equity_curve=equity_curve, trades=self._closed, performance=report)

    # -- timeline ----------------------------------------------------------- #
    def _timeline(self) -> list[pd.Timestamp]:
        stamps: set[pd.Timestamp] = set()
        for d in self.data.values():
            stamps.update(d.index)
        return sorted(stamps)

    # -- order execution ---------------------------------------------------- #
    def _execute(self, orders: Sequence[OrderIntent], ts: pd.Timestamp) -> set[str]:
        opened: set[str] = set()
        for order in orders:
            sym = order.symbol.upper()
            data = self.data.get(sym)
            if data is None:
                continue
            row = data.row(ts)
            if row is None:
                continue  # symbol does not trade this session; order lapses
            bar_open = float(data.open[row])
            if order.kind == "exit":
                self._close_position(sym, bar_open, ts, reason="signal", gapped=False)
            elif order.kind == "entry" and order.quantity > 0:
                if self._open_position(order, bar_open, ts):
                    opened.add(sym)
        return opened

    def _open_position(self, order: OrderIntent, bar_open: float, ts: pd.Timestamp) -> bool:
        sym = order.symbol.upper()
        if sym in self.positions or order.stop_price is None:
            return False  # no pyramiding; a protective stop is mandatory
        fill = self.sim.fill_at(reference_price=bar_open, shares=order.quantity, side=order.side)
        risk_per_share = abs(fill.price - order.stop_price)
        if risk_per_share <= 0:
            return False
        self.cash -= order.side.sign * fill.cash_flow + fill.commission
        self.positions[sym] = _Position(
            symbol=sym,
            side=order.side,
            shares=order.quantity,
            entry_price=fill.price,
            entry_time=ts,
            stop_price=order.stop_price,
            risk_per_share=risk_per_share,
            entry_commission=fill.commission,
            highest=fill.price,
            lowest=fill.price,
        )
        return True

    def _resolve_overnight_stops(
        self, ts: pd.Timestamp, just_opened: set[str], *, intraday_only: bool = False
    ) -> None:
        for sym in list(self.positions):
            if intraday_only and sym not in just_opened:
                continue
            if not intraday_only and sym in just_opened:
                continue
            pos = self.positions[sym]
            data = self.data.get(sym)
            if data is None:
                continue
            row = data.row(ts)
            if row is None:
                continue
            res = self.sim.resolve_stop(
                position_side=pos.side,
                stop_price=pos.stop_price,
                bar_open=float(data.open[row]),
                bar_high=float(data.high[row]),
                bar_low=float(data.low[row]),
                allow_gap=self.config.allow_gap_fills and not intraday_only,
            )
            if res.triggered:
                self._close_position(sym, res.exec_price, ts, reason="stop", gapped=res.gapped)

    # -- position lifecycle ------------------------------------------------- #
    def _update_positions(self, ts: pd.Timestamp) -> None:
        for sym, pos in self.positions.items():
            data = self.data.get(sym)
            if data is None:
                continue
            row = data.row(ts)
            if row is None:
                continue
            pos.highest = max(pos.highest, float(data.high[row]))
            pos.lowest = min(pos.lowest, float(data.low[row]))
            pos.bars_held += 1

    def _close_position(
        self, sym: str, raw_price: float, ts: pd.Timestamp, *, reason: str, gapped: bool
    ) -> None:
        pos = self.positions.pop(sym, None)
        if pos is None:
            return
        exit_side = Side.SHORT if pos.side is Side.LONG else Side.LONG
        fill = self.sim.fill_stop(exec_price=raw_price, shares=pos.shares, exit_side=exit_side)
        self.cash += pos.side.sign * fill.price * pos.shares - fill.commission

        sign = pos.side.sign
        price_move = (fill.price - pos.entry_price) * sign
        pnl = price_move * pos.shares - pos.entry_commission - fill.commission
        r_multiple = price_move / pos.risk_per_share
        # Favorable excursion is the best price in the trade's direction (the bar
        # high for a long, the bar low for a short); adverse is the opposite extreme.
        # Using the wrong extreme made both 0 for every short (after the clamps below).
        favorable = pos.highest if pos.side is Side.LONG else pos.lowest
        adverse = pos.lowest if pos.side is Side.LONG else pos.highest
        mfe_r = (favorable - pos.entry_price) * sign / pos.risk_per_share
        mae_r = (adverse - pos.entry_price) * sign / pos.risk_per_share
        holding_days = max(0, (ts - pos.entry_time).days)
        self._closed.append(
            Trade(
                symbol=sym,
                pnl=pnl,
                r_multiple=r_multiple,
                holding_days=holding_days,
                mae_r=min(0.0, mae_r),
                mfe_r=max(0.0, mfe_r),
                side=pos.side,
                entry_date=pos.entry_time.date(),
                exit_date=ts.date(),
            )
        )

    def _liquidate(self, ts: pd.Timestamp) -> None:
        for sym in list(self.positions):
            data = self.data[sym]
            row = data.row(ts)
            price = float(data.close[row]) if row is not None else self.positions[sym].entry_price
            self._close_position(sym, price, ts, reason="liquidation", gapped=False)

    # -- accounting --------------------------------------------------------- #
    def mark_to_market(self, ts: pd.Timestamp) -> float:
        equity = self.cash
        for sym, pos in self.positions.items():
            data = self.data.get(sym)
            if data is None:
                continue
            row = data.row(ts)
            price = float(data.close[row]) if row is not None else pos.entry_price
            equity += pos.side.sign * price * pos.shares
        return equity
