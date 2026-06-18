"""Trade-intelligence attribution: slice performance by every recorded dimension.

Answers "*where* does the edge come from?" — by sector, market regime, reason
for entry, reason for exit, holding-period bucket and direction. Each slice is
summarised with the same objective-first :class:`TradeStats`, so a sector or
exit-reason is judged on expectancy / profit factor / trend capture, never on
win rate.

These functions are pure (list of :class:`Trade` -> report), so they work the
same on backtest output, paper or live trades pulled from the database.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from momentum.analytics.trade_analysis import Trade, TradeStats, compute_trade_stats

# Holding-period buckets (calendar days) — momentum winners should skew long.
_HOLD_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-1d", 0, 1),
    ("2-5d", 2, 5),
    ("6-20d", 6, 20),
    ("21-60d", 21, 60),
    ("60d+", 61, 10**9),
)

KeyFn = Callable[[Trade], str]


def attribute_by(
    trades: Sequence[Trade], key: KeyFn, *, min_trades: int = 1
) -> dict[str, TradeStats]:
    """Group ``trades`` by ``key`` and summarise each group with TradeStats.

    Groups with fewer than ``min_trades`` are dropped (too few to read into).
    Results are ordered by group expectancy (R), strongest first.
    """
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    stats = {
        name: compute_trade_stats(group)
        for name, group in groups.items()
        if len(group) >= min_trades
    }
    return dict(sorted(stats.items(), key=lambda kv: kv[1].expectancy_r, reverse=True))


def _label(value: str | None) -> str:
    return value if value else "unknown"


def holding_bucket(trade: Trade) -> str:
    """Map a trade's holding period to a labelled bucket."""
    days = trade.holding_days
    for name, lo, hi in _HOLD_BUCKETS:
        if lo <= days <= hi:
            return name
    return "60d+"


def by_sector(trades: Sequence[Trade], *, min_trades: int = 1) -> dict[str, TradeStats]:
    return attribute_by(trades, lambda t: _label(t.sector), min_trades=min_trades)


def by_regime(trades: Sequence[Trade], *, min_trades: int = 1) -> dict[str, TradeStats]:
    return attribute_by(trades, lambda t: _label(t.regime), min_trades=min_trades)


def by_entry_reason(trades: Sequence[Trade], *, min_trades: int = 1) -> dict[str, TradeStats]:
    return attribute_by(trades, lambda t: _label(t.entry_reason), min_trades=min_trades)


def by_exit_reason(trades: Sequence[Trade], *, min_trades: int = 1) -> dict[str, TradeStats]:
    return attribute_by(trades, lambda t: _label(t.exit_reason), min_trades=min_trades)


def by_holding_bucket(trades: Sequence[Trade], *, min_trades: int = 1) -> dict[str, TradeStats]:
    return attribute_by(trades, holding_bucket, min_trades=min_trades)


def by_direction(trades: Sequence[Trade], *, min_trades: int = 1) -> dict[str, TradeStats]:
    return attribute_by(trades, lambda t: t.side.value, min_trades=min_trades)


@dataclass(frozen=True, slots=True)
class TradeIntelligenceReport:
    """Overall stats plus a breakdown along every recorded dimension."""

    overall: TradeStats
    by_sector: dict[str, TradeStats]
    by_regime: dict[str, TradeStats]
    by_entry_reason: dict[str, TradeStats]
    by_exit_reason: dict[str, TradeStats]
    by_holding_bucket: dict[str, TradeStats]
    by_direction: dict[str, TradeStats]

    def best_sector(self) -> str | None:
        return next(iter(self.by_sector), None)  # dicts are expectancy-sorted

    def worst_sector(self) -> str | None:
        return next(reversed(self.by_sector), None) if self.by_sector else None

    def to_dict(self) -> dict[str, Any]:
        def dump(d: dict[str, TradeStats]) -> dict[str, dict[str, float | None]]:
            return {name: stats.headline() for name, stats in d.items()}

        return {
            "overall": self.overall.headline(),
            "by_sector": dump(self.by_sector),
            "by_regime": dump(self.by_regime),
            "by_entry_reason": dump(self.by_entry_reason),
            "by_exit_reason": dump(self.by_exit_reason),
            "by_holding_bucket": dump(self.by_holding_bucket),
            "by_direction": dump(self.by_direction),
        }


def trade_intelligence_report(
    trades: Sequence[Trade], *, min_trades: int = 1
) -> TradeIntelligenceReport:
    """Full attribution across sector, regime, reasons, holding period, direction."""
    return TradeIntelligenceReport(
        overall=compute_trade_stats(trades),
        by_sector=by_sector(trades, min_trades=min_trades),
        by_regime=by_regime(trades, min_trades=min_trades),
        by_entry_reason=by_entry_reason(trades, min_trades=min_trades),
        by_exit_reason=by_exit_reason(trades, min_trades=min_trades),
        by_holding_bucket=by_holding_bucket(trades, min_trades=min_trades),
        by_direction=by_direction(trades, min_trades=min_trades),
    )
