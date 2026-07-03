"""Performance attribution — every dollar earned or lost gets an explanation.

Two complementary, fully-explainable decompositions (no black boxes):

1. **Per-trade identity** — each closed trade's net P&L is split into an
   *additive identity that always sums back to the net*:

   ``net = opportunity − give_back − fees``

   where *opportunity* is the move the scanner actually found (entry → the
   best price seen while the trade was open, MFE) and *give_back* is the part
   of that move trade management did not capture (exit below the high-water
   mark). A negative-opportunity trade was a bad selection; a large give-back
   on a large opportunity was bad management.

2. **Driver tables** — net dollars grouped by what drove the trade: market
   regime, sector, entry reason (scanner quality), exit reason (stop
   management), holding-period bucket (timing) and instrument (options
   selection). Each row reports n, dollars, share of total.

Plus a **sizing effect**: actual dollars vs the counterfactual where every
trade risked the account-average risk (`r_multiple × avg_risk`). The
difference is exactly what position sizing added or cost.

Pure: a list of :class:`DollarTrade` in, an :class:`AttributionReport` out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_HOLD_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-1d", 0, 1),
    ("2-5d", 2, 5),
    ("6-20d", 6, 20),
    ("21-60d", 21, 60),
    ("60d+", 61, 10**9),
)


@dataclass(frozen=True, slots=True)
class DollarTrade:
    """One closed trade with the facts attribution needs (all in dollars)."""

    symbol: str
    net_pnl: float
    fees: float = 0.0
    opportunity: float | None = None  # (MFE - entry) x qty x mult; None = unknown
    r_multiple: float | None = None
    initial_risk: float | None = None  # $ risked at entry
    holding_days: int = 0
    sector: str | None = None
    regime: str | None = None
    entry_reason: str | None = None
    exit_reason: str | None = None
    instrument: str = "shares"


@dataclass(frozen=True, slots=True)
class TradeAttribution:
    """The per-trade identity: net = opportunity − give_back − fees."""

    symbol: str
    net_pnl: float
    opportunity: float | None
    give_back: float | None  # opportunity − gross; None when MFE unknown
    fees: float
    capture_ratio: float | None  # gross / opportunity (winners' trend capture)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "net_pnl": round(self.net_pnl, 2),
            "opportunity": round(self.opportunity, 2) if self.opportunity is not None else None,
            "give_back": round(self.give_back, 2) if self.give_back is not None else None,
            "fees": round(self.fees, 2),
            "capture_ratio": (
                round(self.capture_ratio, 3) if self.capture_ratio is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class DriverRow:
    """One group's contribution to the total."""

    driver: str
    label: str
    num_trades: int
    net_pnl: float
    share_of_total: float | None  # of the report's total net (None when net ~ 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "label": self.label,
            "num_trades": self.num_trades,
            "net_pnl": round(self.net_pnl, 2),
            "share_of_total": (
                round(self.share_of_total, 3) if self.share_of_total is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class AttributionReport:
    total_net_pnl: float
    total_fees: float
    total_opportunity: float  # over trades with a known MFE
    total_give_back: float
    trades_with_opportunity: int
    sizing_effect: float | None  # actual − equal-risk counterfactual
    sizing_baseline_risk: float | None
    per_trade: tuple[TradeAttribution, ...]
    drivers: tuple[DriverRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_net_pnl": round(self.total_net_pnl, 2),
            "total_fees": round(self.total_fees, 2),
            "total_opportunity": round(self.total_opportunity, 2),
            "total_give_back": round(self.total_give_back, 2),
            "trades_with_opportunity": self.trades_with_opportunity,
            "sizing_effect": round(self.sizing_effect, 2)
            if self.sizing_effect is not None
            else None,
            "sizing_baseline_risk": (
                round(self.sizing_baseline_risk, 2)
                if self.sizing_baseline_risk is not None
                else None
            ),
            "per_trade": [t.to_dict() for t in self.per_trade],
            "drivers": [d.to_dict() for d in self.drivers],
        }


def _hold_bucket(days: int) -> str:
    for label, low, high in _HOLD_BUCKETS:
        if low <= days <= high:
            return label
    return _HOLD_BUCKETS[-1][0]


def _driver_rows(trades: list[DollarTrade], driver: str, key: Any, total: float) -> list[DriverRow]:
    groups: dict[str, list[DollarTrade]] = {}
    for trade in trades:
        label = key(trade)
        if label is None:
            label = "unknown"
        groups.setdefault(str(label), []).append(trade)
    rows = []
    for label, members in groups.items():
        net = sum(t.net_pnl for t in members)
        rows.append(
            DriverRow(
                driver=driver,
                label=label,
                num_trades=len(members),
                net_pnl=net,
                share_of_total=net / total if abs(total) > 1e-9 else None,
            )
        )
    rows.sort(key=lambda r: r.net_pnl, reverse=True)
    return rows


def attribute_dollars(trades: list[DollarTrade]) -> AttributionReport:
    """The full attribution (pure, total; empty input yields a zero report)."""
    per_trade: list[TradeAttribution] = []
    total_opportunity = 0.0
    total_give_back = 0.0
    with_opportunity = 0
    for trade in trades:
        gross = trade.net_pnl + trade.fees
        opportunity = trade.opportunity
        give_back: float | None = None
        capture: float | None = None
        if opportunity is not None:
            give_back = opportunity - gross
            total_opportunity += opportunity
            total_give_back += give_back
            with_opportunity += 1
            if opportunity > 0:
                capture = gross / opportunity
        per_trade.append(
            TradeAttribution(
                symbol=trade.symbol,
                net_pnl=trade.net_pnl,
                opportunity=opportunity,
                give_back=give_back,
                fees=trade.fees,
                capture_ratio=capture,
            )
        )

    total = sum(t.net_pnl for t in trades)

    # Sizing effect: actual vs "risk the average on every trade".
    sized = [t for t in trades if t.r_multiple is not None and t.initial_risk is not None]
    sizing_effect: float | None = None
    baseline: float | None = None
    if len(sized) >= 2:
        baseline = sum(t.initial_risk or 0.0 for t in sized) / len(sized)
        counterfactual = sum((t.r_multiple or 0.0) * baseline for t in sized)
        actual = sum((t.r_multiple or 0.0) * (t.initial_risk or 0.0) for t in sized)
        sizing_effect = actual - counterfactual

    drivers: list[DriverRow] = []
    drivers += _driver_rows(trades, "regime", lambda t: t.regime, total)
    drivers += _driver_rows(trades, "sector", lambda t: t.sector, total)
    drivers += _driver_rows(trades, "entry_reason", lambda t: t.entry_reason, total)
    drivers += _driver_rows(trades, "exit_reason", lambda t: t.exit_reason, total)
    drivers += _driver_rows(trades, "holding_period", lambda t: _hold_bucket(t.holding_days), total)
    drivers += _driver_rows(trades, "instrument", lambda t: t.instrument, total)

    return AttributionReport(
        total_net_pnl=total,
        total_fees=sum(t.fees for t in trades),
        total_opportunity=total_opportunity,
        total_give_back=total_give_back,
        trades_with_opportunity=with_opportunity,
        sizing_effect=sizing_effect,
        sizing_baseline_risk=baseline,
        per_trade=tuple(sorted(per_trade, key=lambda t: t.net_pnl)),
        drivers=tuple(drivers),
    )
