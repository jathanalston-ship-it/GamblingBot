"""The daily orchestration engine — one cycle of the paper trading system.

:class:`DailyOrchestrationEngine` runs a full session end to end and is the
**single source of truth** wiring: it owns no in-memory account state of its own.
Each :meth:`run_day` call:

1. **Recovers** the portfolio from the persisted trade ledger (crash recovery).
2. Marks open positions to the day's prices and records a ``running`` run row.
3. **Manages exits** — closes positions that hit a stop / target / time stop.
4. **Runs entries** — delegates to :class:`DailyPaperPipeline` (scan → conviction
   → risk sizing → paper order → position tracking → journal).
5. **Persists** the run outcome and returns a :class:`DailyReport`.

State is committed incrementally and the run is flipped to ``completed`` /
``failed`` so a crash is recoverable: a re-run reconstructs from the committed
ledger and the idempotent journal / held-symbol guards prevent double work.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from momentum.conviction.engine import ConvictionBand, ConvictionEngine
from momentum.core.enums import RegimeState, Side
from momentum.execution.broker import Broker, OrderRequest
from momentum.orchestration.daily_report import DailyReport, tally_outcomes
from momentum.orchestration.exits import ExitManager, ExitSignal
from momentum.orchestration.pipeline import DailyPaperPipeline
from momentum.orchestration.recovery import reconstruct_portfolio
from momentum.portfolio.journal import TradeJournal
from momentum.portfolio.portfolio import Portfolio
from momentum.persistence.audit import AuditLogger
from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot
from momentum.persistence.models.risk_metric import RiskMetric
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.portfolio_snapshots import PortfolioSnapshotRepository
from momentum.persistence.repositories.risk_metrics import RiskMetricRepository
from momentum.persistence.repositories.runs import RunRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_budget import DynamicRiskBudgetEngine
from momentum.risk.risk_manager import RiskManager
from momentum.universe.screener import ScanResult

_EOD = dt.time(16, 0)


def _risk_stats(closed: list[Any]) -> dict[str, float | int | None]:
    """Basic per-session trade stats from the run's closed trades (pure)."""
    rs = [float(t.r_multiple) for t in closed if t.r_multiple is not None]
    n = len(rs)
    if n == 0:
        return {
            "num_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "expectancy_r": None,
            "avg_win_r": None,
            "avg_loss_r": None,
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "num_trades": n,
        "win_rate": round(len(wins) / n, 4),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "expectancy_r": round(sum(rs) / n, 4),
        "avg_win_r": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss_r": round(sum(losses) / len(losses), 4) if losses else None,
    }


def build_snapshot(
    portfolio: Portfolio, *, run_id: str, as_of: dt.date, when: dt.datetime
) -> PortfolioSnapshot:
    """A ``portfolio_snapshots`` row from the live account state (pure)."""
    equity = portfolio.equity
    peak = max(portfolio.peak_equity, equity)
    return PortfolioSnapshot(
        run_id=run_id,
        as_of=when,
        session_date=as_of,
        equity=round(equity, 2),
        cash=round(portfolio.cash, 2),
        positions_value=round(portfolio.positions_market_value, 2),
        num_positions=len(portfolio.positions),
        realized_pnl=round(portfolio.realized_pnl, 2),
        unrealized_pnl=round(portfolio.unrealized_pnl, 2),
        high_water_mark=round(peak, 2),
        drawdown=round(max(0.0, 1.0 - equity / peak), 4) if peak > 0 else 0.0,
        cumulative_return=(
            round(equity / portfolio.starting_equity - 1.0, 4)
            if portfolio.starting_equity > 0
            else None
        ),
    )


def build_risk_metric(
    closed: list[Any],
    snapshot: PortfolioSnapshot,
    *,
    run_id: str,
    as_of: dt.date,
    when: dt.datetime,
) -> RiskMetric:
    """A basic ``risk_metrics`` row from the run's closed trades (pure)."""
    stats = _risk_stats(closed)
    return RiskMetric(
        run_id=run_id,
        as_of=when,
        session_date=as_of,
        scope="portfolio",
        window="inception",
        num_trades=stats["num_trades"],
        win_rate=stats["win_rate"],
        profit_factor=stats["profit_factor"],
        expectancy_r=stats["expectancy_r"],
        avg_win_r=stats["avg_win_r"],
        avg_loss_r=stats["avg_loss_r"],
        current_drawdown=(-snapshot.drawdown if snapshot.drawdown is not None else None),
    )


class DailyOrchestrationEngine:
    """Runs the recover → exits → entries → persist cycle for one trading day."""

    def __init__(
        self,
        *,
        conviction: ConvictionEngine,
        risk: RiskManager,
        broker: Broker,
        starting_equity: float,
        exit_manager: ExitManager | None = None,
        risk_budget: DynamicRiskBudgetEngine | None = None,
        min_conviction_band: ConvictionBand = ConvictionBand.MEDIUM,
        mode: str = "paper",
        entry_reason: str = "momentum_breakout",
        enable_audit: bool = True,
        persist_portfolio: bool = True,
    ) -> None:
        self.conviction = conviction
        self.risk = risk
        self.broker = broker
        self.starting_equity = starting_equity
        self.exit_manager = exit_manager or ExitManager()
        self.risk_budget = risk_budget or DynamicRiskBudgetEngine()
        self.min_conviction_band = min_conviction_band
        self.mode = mode
        self.entry_reason = entry_reason
        self.enable_audit = enable_audit
        self.persist_portfolio = persist_portfolio

    def run_day(
        self,
        session: Session,
        *,
        scan: ScanResult,
        marks: dict[str, float],
        as_of: dt.date,
        run_id: str | None = None,
        regime: RegimeState | None = None,
        ts: dt.datetime | None = None,
    ) -> DailyReport:
        """Run one full daily cycle and return its report."""
        run_id = run_id or f"{self.mode}-{as_of:%Y%m%d}"
        when = ts or dt.datetime.combine(as_of, _EOD, tzinfo=dt.UTC)
        trades = TradeRepository(session)
        runs = RunRepository(session)
        journal = TradeJournal(trades)
        audit = AuditLogger(AuditLogRepository(session)) if self.enable_audit else None

        # 1-2. Recover the account from the ledger; record a durable running marker.
        portfolio = reconstruct_portfolio(trades, starting_equity=self.starting_equity, marks=marks)
        equity_start = portfolio.equity
        run = runs.start(
            run_id=run_id,
            mode=self.mode,
            as_of=as_of,
            started_at=when,
            config_hash=self.exit_manager.config.config_hash(),
            equity_start=equity_start,
        )
        session.commit()

        try:
            # 3. Manage exits on the recovered book.
            closed = self._manage_exits(
                portfolio, journal, trades, audit, marks, as_of, when, run_id
            )
            session.commit()

            # 4. Run entries through the paper pipeline (shares the live portfolio).
            pipeline = DailyPaperPipeline(
                conviction=self.conviction,
                risk=self.risk,
                broker=self.broker,
                portfolio=portfolio,
                journal=journal,
                risk_budget=self.risk_budget,
                min_conviction_band=self.min_conviction_band,
                entry_reason=self.entry_reason,
                audit=audit,
            )
            report = pipeline.run(scan, run_id=run_id, regime=regime, ts=when)
            opened = [d.to_dict() for d in report.opened]
            outcomes = tally_outcomes([d.outcome for d in report.decisions])
            session.commit()

            # 5. Persist the run outcome.
            runs.complete(
                run,
                finished_at=when,
                equity_end=portfolio.equity,
                num_opened=len(opened),
                num_closed=len(closed),
            )
            session.commit()

            # 6. Persist an end-of-session equity snapshot + basic risk metric so
            #    the Portfolio screen populates from live activity (idempotent).
            if self.persist_portfolio:
                self._persist_portfolio(session, portfolio, trades, as_of, when, run_id)
                session.commit()
        except Exception as exc:  # record the failure durably, then re-raise
            session.rollback()
            failed = runs.get(run_id)
            if failed is not None:
                runs.fail(failed, finished_at=when, error=f"{type(exc).__name__}: {exc}")
                session.commit()
            raise

        return DailyReport(
            run_id=run_id,
            as_of=as_of,
            mode=self.mode,
            equity_start=equity_start,
            equity_end=portfolio.equity,
            cash_end=portfolio.cash,
            realized_pnl=portfolio.realized_pnl,
            unrealized_pnl=portfolio.unrealized_pnl,
            num_open_positions=len(portfolio.positions),
            opened=tuple(opened),
            closed=tuple(closed),
            entry_outcomes=outcomes,
        )

    # -- portfolio persistence ---------------------------------------------- #
    def _persist_portfolio(
        self,
        session: Session,
        portfolio: Portfolio,
        trades: TradeRepository,
        as_of: dt.date,
        when: dt.datetime,
        run_id: str,
    ) -> None:
        """Write the session's equity snapshot + basic risk metric (idempotent)."""
        snapshot = build_snapshot(portfolio, run_id=run_id, as_of=as_of, when=when)
        PortfolioSnapshotRepository(session).save(snapshot)
        closed_trades = list(trades.closed(run_id))
        metric = build_risk_metric(closed_trades, snapshot, run_id=run_id, as_of=as_of, when=when)
        RiskMetricRepository(session).save(metric)

    # -- exits -------------------------------------------------------------- #
    def _manage_exits(
        self,
        portfolio: Portfolio,
        journal: TradeJournal,
        trades: TradeRepository,
        audit: AuditLogger | None,
        marks: dict[str, float],
        as_of: dt.date,
        ts: dt.datetime,
        run_id: str,
    ) -> list[dict[str, Any]]:
        closed: list[dict[str, Any]] = []
        for signal in self.exit_manager.exits(portfolio.open_positions, marks, as_of):
            position = portfolio.positions[signal.symbol]
            exit_side = Side.SHORT if position.side is Side.LONG else Side.LONG
            order = self.broker.submit(
                OrderRequest(
                    client_order_id=f"{run_id}:exit:{signal.symbol}",
                    symbol=signal.symbol,
                    side=exit_side,
                    quantity=signal.quantity,
                    reference_price=signal.price,
                    ts=ts,
                )
            )
            if audit is not None:
                audit.order_submitted(order, ts=ts, run_id=run_id)
            if not order.is_filled:
                continue
            fill = order.fills[-1]
            portfolio.on_fill(fill)
            trade = trades.open_for_symbol(signal.symbol)
            if trade is None:
                continue
            closed_trade = journal.close_trade(trade, fill, exit_reason=signal.reason)
            if audit is not None:
                audit.order_filled(order, fill, run_id=run_id)
                audit.position_closed(closed_trade, reason=signal.reason, run_id=run_id)
            closed.append(_closed_record(signal, closed_trade))
        return closed


def _closed_record(signal: ExitSignal, trade: Any) -> dict[str, Any]:
    return {
        "symbol": signal.symbol,
        "reason": signal.reason,
        "exit_price": trade.exit_price,
        "quantity": trade.quantity,
        "r_multiple": trade.r_multiple,
        "net_pnl": trade.net_pnl,
    }
