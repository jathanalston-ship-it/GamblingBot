"""Read helpers for the strategy: the market gate, account equity, the rules.

Thin glue between stored rows and :mod:`momentum.strategy` — no decisions are
made here. The **market gate** is written by every scan onto the regime row
(``details["market_gate"]``) and read back by verdicts, Auto Pilot, the trade
plan and the UI, so they all agree on whether new entries are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.trade import Trade
from momentum.strategy import StrategyConfig, default_config


@dataclass(frozen=True, slots=True)
class MarketGate:
    """Whether the strategy may open new positions, with the evidence."""

    uptrend: bool | None  # None = unknown (no scan yet / too little history)
    close: float | None
    average: float | None
    period: int
    symbol: str
    as_of: str | None

    @property
    def entries_allowed(self) -> bool:
        """Unknown is treated as closed — never buy on missing evidence."""
        return self.uptrend is True

    @property
    def headline(self) -> str:
        if self.uptrend is True:
            return "Market is in an uptrend — new buys are allowed"
        if self.uptrend is False:
            return "Market is in a downtrend — no new buys"
        return "Market trend unknown — run a scan"

    @property
    def detail(self) -> str:
        if self.close is None or self.average is None:
            return (
                f"The strategy only buys while {self.symbol} is above its "
                f"{self.period}-day average. No completed scan has measured it yet."
            )
        gap = (self.close / self.average - 1.0) * 100.0 if self.average else 0.0
        side = "above" if gap >= 0 else "below"
        return (
            f"{self.symbol} closed at {self.close:,.2f}, {abs(gap):.1f}% {side} its "
            f"{self.period}-day average ({self.average:,.2f}). "
            + (
                "Existing positions keep their own stops and exits."
                if self.uptrend is False
                else "Buy signals are live."
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uptrend": self.uptrend,
            "entries_allowed": self.entries_allowed,
            "close": self.close,
            "average": self.average,
            "period": self.period,
            "symbol": self.symbol,
            "as_of": self.as_of,
            "headline": self.headline,
            "detail": self.detail,
        }


def market_gate(session: Session, strategy: StrategyConfig | None = None) -> MarketGate:
    """The latest stored market gate (falls back to the regime row's own
    close-vs-slow-average for rows written before the gate was recorded)."""
    cfg = strategy or default_config()
    row = session.scalars(select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)).first()
    if row is None:
        return MarketGate(None, None, None, cfg.regime_ma_period, "SPY", None)
    details = row.details if isinstance(row.details, dict) else {}
    gate = details.get("market_gate")
    as_of = row.as_of.isoformat()
    if isinstance(gate, dict):
        uptrend = gate.get("uptrend")
        return MarketGate(
            uptrend=uptrend if isinstance(uptrend, bool) else None,
            close=_num(gate.get("close")),
            average=_num(gate.get("average")),
            period=int(gate.get("period") or cfg.regime_ma_period),
            symbol=str(gate.get("symbol") or row.benchmark_symbol),
            as_of=as_of,
        )
    close, average = row.benchmark_close, row.ma_slow
    uptrend = (close > average) if close is not None and average is not None else None
    return MarketGate(uptrend, close, average, cfg.regime_ma_period, row.benchmark_symbol, as_of)


def account_equity(session: Session) -> float:
    """The paper account's current equity: starting balance + realized P&L +
    open P&L at each position's last evaluated price (cost when never marked)."""
    from momentum.api import user_settings
    from momentum.persistence.models.tracked_trade import TrackedTrade
    from momentum.persistence.repositories.trade_evaluations import TradeEvaluationRepository

    starting = user_settings.read_account_balance()
    equity = starting
    uid_by_journal: dict[int, str] = {}
    for journal_id, uid in session.execute(
        select(TrackedTrade.journal_trade_id, TrackedTrade.trade_uid).where(
            TrackedTrade.journal_trade_id.is_not(None), TrackedTrade.status == "open"
        )
    ):
        if journal_id is not None:
            uid_by_journal[int(journal_id)] = str(uid)
    evaluations = TradeEvaluationRepository(session)
    for trade in session.scalars(select(Trade)):
        if trade.status == "closed":
            equity += trade.net_pnl or 0.0
            continue
        equity += trade.scaled_out_pnl or 0.0
        tracked_uid = uid_by_journal.get(trade.id)
        latest = evaluations.latest_for(tracked_uid) if tracked_uid is not None else None
        if latest is not None and latest.price is not None:
            equity += (latest.price - trade.entry_price) * trade.quantity
    return equity if equity > 0 else starting


def rules_summary(strategy: StrategyConfig | None = None) -> dict[str, Any]:
    """The strategy in plain language + its numbers (for the UI's "How it works")."""
    cfg = strategy or default_config()
    months = ", ".join(f"{round(p / 21)}" for p in sorted(cfg.momentum_lookbacks))
    return {
        "model_version": cfg.model_version,
        "config": cfg.model_dump(),
        "rules": [
            {
                "title": "Only buy in a rising market",
                "text": (
                    f"New positions are opened only while SPY is above its "
                    f"{cfg.regime_ma_period}-day average. In a falling market the app "
                    "stops buying and waits."
                ),
            },
            {
                "title": "Buy leaders that are breaking out",
                "text": (
                    f"A stock is a buy signal when its {months}-month performance is in "
                    f"the top {round((1 - cfg.min_momentum_rank) * 100)}% of the universe, "
                    f"it trades above its own {cfg.trend_ma_period}-day average, and it "
                    f"made a new {cfg.breakout_lookback}-day high in the last "
                    f"{cfg.breakout_within} sessions."
                ),
            },
            {
                "title": "Risk a small, fixed amount",
                "text": (
                    f"Each trade risks {cfg.risk_per_trade_pct * 100:g}% of the account. "
                    f"The stop sits {cfg.stop_atr_mult:g}× the stock's average daily range "
                    f"below the entry, no position is larger than "
                    f"{cfg.max_position_pct * 100:g}% of the account, and at most "
                    f"{cfg.max_positions} positions are open at once."
                ),
            },
            {
                "title": "Cut losers, let winners run",
                "text": (
                    f"There is no profit target. A position is sold when it hits its stop "
                    f"or closes below its {cfg.exit_lookback}-day low. Most trades are "
                    "small losses; a few large winners make the money."
                ),
            },
        ],
    }


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
