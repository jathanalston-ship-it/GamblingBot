"""Automated weekly research reporting — evidence only, never auto-tuning.

Once a week this reads everything that happened — **all trades, all signals, all
market regimes** for the period — runs the objective-first analytics, and
synthesises an evidence report: *what worked*, *what failed*, the *largest
winners and losers*, and *potential improvements*.

Hard guarantees:

* **Read-only.** It queries the database and writes exactly one artefact: a
  ``research_reports`` row. It never edits config, strategy or any tunable.
* **Evidence, not action.** "Potential improvements" are framed as hypotheses
  for a human to review — the system does not act on them.

Outputs: a markdown report (:meth:`WeeklyResearchReport.to_markdown`), a JSON
report (:meth:`to_json`) and a database record (:meth:`to_record` + the
``ResearchReportRepository``).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.analytics.attribution import TradeIntelligenceReport, trade_intelligence_report
from momentum.analytics.trade_analysis import Trade as AnalyticsTrade
from momentum.analytics.trade_analysis import TradeStats, compute_trade_stats
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.repositories.signals import SignalRepository
from momentum.persistence.repositories.trades import TradeRepository, to_analytics_trade

READ_ONLY_NOTICE = (
    "This report is **evidence only**. The research system is read-only: it does "
    "not modify the strategy, risk or any configuration. Improvements are "
    "hypotheses for human review, never applied automatically."
)

_MIN_SLICE_TRADES = 3  # don't read into slices thinner than this


@dataclass(frozen=True, slots=True)
class WeeklyResearchReport:
    """A week's research evidence, ready to render and persist."""

    period_start: dt.date
    period_end: dt.date
    generated_at: dt.datetime
    run_id: str | None

    # scope
    num_trades: int
    num_signals: int
    num_regimes: int

    # analysis
    trades: TradeStats
    intelligence: TradeIntelligenceReport
    net_pnl: float
    max_drawdown_r: float
    signal_status: dict[str, int]
    signal_types: dict[str, int]
    acceptance_rate: float | None
    regime_distribution: dict[str, int]
    latest_regime: str | None

    # findings
    largest_winners: list[dict[str, Any]]
    largest_losers: list[dict[str, Any]]
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "period": {
                "start": self.period_start.isoformat(),
                "end": self.period_end.isoformat(),
                "generated_at": self.generated_at.isoformat(),
                "run_id": self.run_id,
            },
            "scope": {
                "num_trades": self.num_trades,
                "num_signals": self.num_signals,
                "num_regimes": self.num_regimes,
            },
            "objective": self.trades.headline(),
            "pnl": {"net_pnl": self.net_pnl, "max_drawdown_r": self.max_drawdown_r},
            "signals": {
                "by_status": self.signal_status,
                "by_type": self.signal_types,
                "acceptance_rate": self.acceptance_rate,
            },
            "regimes": {
                "distribution": self.regime_distribution,
                "latest": self.latest_regime,
            },
            "attribution": self.intelligence.to_dict(),
            "findings": {
                "what_worked": self.what_worked,
                "what_failed": self.what_failed,
                "largest_winners": self.largest_winners,
                "largest_losers": self.largest_losers,
                "potential_improvements": self.improvements,
            },
            "notice": READ_ONLY_NOTICE,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        return _render_markdown(self)

    def to_record(self) -> dict[str, Any]:
        """Kwargs for the ``research_reports`` table."""
        pf = self.trades.profit_factor
        return {
            "run_id": self.run_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "num_trades": self.num_trades,
            "num_signals": self.num_signals,
            "num_regimes": self.num_regimes,
            "expectancy_r": self.trades.expectancy_r,
            "profit_factor": None if pf == float("inf") else pf,
            "win_rate": self.trades.win_rate,
            "net_pnl": self.net_pnl,
            "trend_capture": self.trades.trend_capture,
            "max_drawdown": self.max_drawdown_r,
            "report_json": self.to_dict(),
            "markdown": self.to_markdown(),
        }


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def generate_weekly_report(
    session: Session,
    *,
    period_end: dt.date | None = None,
    period_days: int = 7,
    run_id: str | None = None,
    top_n: int = 5,
    now: dt.datetime | None = None,
) -> WeeklyResearchReport:
    """Build the research report for the ``period_days`` ending ``period_end``."""
    period_end = period_end or dt.date.today()
    period_start = period_end - dt.timedelta(days=period_days - 1)

    trade_rows = TradeRepository(session).closed_between(period_start, period_end, run_id)
    atrades = [to_analytics_trade(t) for t in trade_rows]
    signals = SignalRepository(session).between(period_start, period_end, run_id)
    regimes = _regimes_between(session, period_start, period_end)

    stats = compute_trade_stats(atrades)
    intelligence = trade_intelligence_report(atrades, min_trades=1)
    regime_dist = _tally_regimes(regimes)

    what_worked, what_failed, improvements = _build_findings(
        stats, intelligence, atrades, signals, regime_dist
    )

    return WeeklyResearchReport(
        period_start=period_start,
        period_end=period_end,
        generated_at=now or dt.datetime.now(tz=dt.timezone.utc),
        run_id=run_id,
        num_trades=len(atrades),
        num_signals=len(signals),
        num_regimes=len(regimes),
        trades=stats,
        intelligence=intelligence,
        net_pnl=round(sum(t.pnl for t in atrades), 2),
        max_drawdown_r=_max_drawdown_r(atrades),
        signal_status=SignalRepository.tally(signals, "status"),
        signal_types=SignalRepository.tally(signals, "signal_type"),
        acceptance_rate=SignalRepository.acceptance_rate(signals),
        regime_distribution=regime_dist,
        latest_regime=(regimes[-1].regime if regimes else None),
        largest_winners=_extremes(atrades, top_n, winners=True),
        largest_losers=_extremes(atrades, top_n, winners=False),
        what_worked=what_worked,
        what_failed=what_failed,
        improvements=improvements,
    )


def run_weekly_report(
    session: Session,
    *,
    period_end: dt.date | None = None,
    run_id: str | None = None,
    persist: bool = True,
) -> WeeklyResearchReport:
    """Generate the weekly report and (by default) persist the DB record.

    Intended to be invoked by a weekly scheduler/cron. Returns the report;
    persistence is the only side effect and is idempotent per (run_id, period).
    """
    report = generate_weekly_report(session, period_end=period_end, run_id=run_id)
    if persist:
        # imported here to keep the report object usable without a live session
        from momentum.persistence.repositories.research_reports import (
            ResearchReportRepository,
        )

        ResearchReportRepository(session).save(report.to_record())
    return report


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
def _regimes_between(session: Session, start: dt.date, end: dt.date) -> list[MarketRegime]:
    stmt = (
        select(MarketRegime)
        .where(MarketRegime.as_of >= start, MarketRegime.as_of <= end)
        .order_by(MarketRegime.as_of.asc())
    )
    return list(session.scalars(stmt).all())


def _tally_regimes(regimes: Sequence[MarketRegime]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in regimes:
        counts[r.regime] = counts.get(r.regime, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def _max_drawdown_r(trades: Sequence[AnalyticsTrade]) -> float:
    """Worst peak-to-trough of cumulative R over the period (<= 0)."""
    cum = 0.0
    peak = 0.0
    worst = 0.0
    for t in trades:
        cum += t.r_multiple
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return round(worst, 4)


def _extremes(trades: Sequence[AnalyticsTrade], n: int, *, winners: bool) -> list[dict[str, Any]]:
    ordered = sorted(trades, key=lambda t: t.r_multiple, reverse=winners)
    picked = [t for t in ordered if (t.r_multiple > 0) == winners][:n]
    return [
        {
            "symbol": t.symbol,
            "r_multiple": round(t.r_multiple, 3),
            "pnl": round(t.pnl, 2),
            "holding_days": t.holding_days,
            "sector": t.sector,
            "regime": t.regime,
            "entry_reason": t.entry_reason,
            "exit_reason": t.exit_reason,
        }
        for t in picked
    ]


# --------------------------------------------------------------------------- #
# Findings synthesis (evidence only)
# --------------------------------------------------------------------------- #
def _best(groups: dict[str, TradeStats]) -> tuple[str, TradeStats] | None:
    items = [(k, v) for k, v in groups.items() if v.num_trades >= _MIN_SLICE_TRADES]
    return max(items, key=lambda kv: kv[1].expectancy_r) if items else None


def _worst(groups: dict[str, TradeStats]) -> tuple[str, TradeStats] | None:
    items = [(k, v) for k, v in groups.items() if v.num_trades >= _MIN_SLICE_TRADES]
    return min(items, key=lambda kv: kv[1].expectancy_r) if items else None


def _build_findings(
    stats: TradeStats,
    intel: TradeIntelligenceReport,
    trades: Sequence[AnalyticsTrade],
    signals: Sequence[Any],
    regime_dist: dict[str, int],
) -> tuple[list[str], list[str], list[str]]:
    worked: list[str] = []
    failed: list[str] = []
    improvements: list[str] = []

    if stats.num_trades == 0:
        return (
            ["No closed trades this period — nothing to evaluate."],
            [],
            ["Insufficient data: no trades closed. Evidence only — no action."],
        )

    # --- what worked --------------------------------------------------- #
    if stats.expectancy_r > 0:
        worked.append(
            f"Positive expectancy {stats.expectancy_r:.2f}R over {stats.num_trades} "
            f"trades (profit factor {_pf(stats.profit_factor)})."
        )
    if stats.winner_loser_hold_ratio > 1.2:
        worked.append(
            f"Let-winners-run intact: winners held "
            f"{stats.winner_loser_hold_ratio:.1f}x longer than losers."
        )
    if stats.trend_capture is not None and stats.trend_capture >= 0.7:
        worked.append(f"Strong trend capture: kept {stats.trend_capture:.0%} of favourable moves.")
    best_sector = _best(intel.by_sector)
    if best_sector and best_sector[1].expectancy_r > 0:
        worked.append(
            f"Best sector '{best_sector[0]}': {best_sector[1].expectancy_r:.2f}R "
            f"over {best_sector[1].num_trades} trades."
        )
    best_setup = _best(intel.by_entry_reason)
    if best_setup and best_setup[1].expectancy_r > 0:
        worked.append(
            f"Best setup '{best_setup[0]}': {best_setup[1].expectancy_r:.2f}R "
            f"over {best_setup[1].num_trades} trades."
        )

    # --- what failed --------------------------------------------------- #
    if stats.expectancy_r <= 0:
        failed.append(
            f"Negative expectancy {stats.expectancy_r:.2f}R over {stats.num_trades} trades."
        )
    worst_sector = _worst(intel.by_sector)
    if worst_sector and worst_sector[1].expectancy_r < 0:
        failed.append(
            f"Weakest sector '{worst_sector[0]}': {worst_sector[1].expectancy_r:.2f}R "
            f"over {worst_sector[1].num_trades} trades."
        )
    worst_setup = _worst(intel.by_entry_reason)
    if worst_setup and worst_setup[1].expectancy_r < 0:
        failed.append(
            f"Weakest setup '{worst_setup[0]}': {worst_setup[1].expectancy_r:.2f}R "
            f"over {worst_setup[1].num_trades} trades."
        )
    if stats.largest_loser_r < -1.01:
        failed.append(
            f"Largest loss {stats.largest_loser_r:.2f}R exceeded the -1R budget "
            f"(gap or slippage beyond stop)."
        )
    # exits that give back trend
    early_exit = _worst_trend_capture_exit(intel.by_exit_reason)
    if early_exit is not None:
        name, tc = early_exit
        failed.append(f"Exit '{name}' captured only {tc:.0%} of available trend.")

    # --- potential improvements (hypotheses, NOT applied) -------------- #
    if stats.num_trades < 20:
        improvements.append(
            f"Low sample ({stats.num_trades} trades): treat all findings as "
            f"low-confidence; do not act on a single week."
        )
    if worst_sector and worst_sector[1].expectancy_r < 0:
        improvements.append(
            f"Hypothesis: investigate sector '{worst_sector[0]}' "
            f"({worst_sector[1].expectancy_r:.2f}R, {worst_sector[1].num_trades} trades) — "
            f"is it a regime artefact or a persistent drag? Evidence only."
        )
    if early_exit is not None:
        improvements.append(
            f"Hypothesis: exit '{early_exit[0]}' may be premature "
            f"(trend capture {early_exit[1]:.0%}); study wider trails offline. Not applied."
        )
    rate = SignalRepository.acceptance_rate(signals) if signals else None
    if rate is not None and rate < 0.25:
        improvements.append(
            f"Only {rate:.0%} of signals were accepted by the risk gateway — "
            f"review whether veto reasons are intended. Evidence only."
        )
    improvements.append("All items above are evidence for human review — none are auto-applied.")

    return worked, failed, improvements


def _worst_trend_capture_exit(
    by_exit: dict[str, TradeStats], *, threshold: float = 0.5
) -> tuple[str, float] | None:
    candidates = [
        (name, s.trend_capture)
        for name, s in by_exit.items()
        if s.num_trades >= _MIN_SLICE_TRADES and s.trend_capture is not None and s.num_winners > 0
    ]
    below = [(n, tc) for n, tc in candidates if tc is not None and tc < threshold]
    return min(below, key=lambda kv: kv[1]) if below else None


def _pf(value: float) -> str:
    return "∞" if value == float("inf") else f"{value:.2f}"


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #
def _bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- _(none)_"


def _trade_table(rows: Sequence[dict[str, Any]]) -> str:
    header = "| symbol | R | pnl | held | sector | regime | entry | exit |"
    sep = "|---|---|---|---|---|---|---|---|"
    if not rows:
        return header + "\n" + sep + "\n| _(none)_ | | | | | | | |"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['symbol']} | {r['r_multiple']:+.2f} | {r['pnl']:+,.0f} | "
            f"{r['holding_days']}d | {r['sector'] or '—'} | {r['regime'] or '—'} | "
            f"{r['entry_reason'] or '—'} | {r['exit_reason'] or '—'} |"
        )
    return "\n".join(lines)


def _render_markdown(r: WeeklyResearchReport) -> str:
    o = r.trades
    regimes = ", ".join(f"{k}: {v}" for k, v in r.regime_distribution.items()) or "—"
    statuses = ", ".join(f"{k}: {v}" for k, v in r.signal_status.items()) or "—"
    rate = "—" if r.acceptance_rate is None else f"{r.acceptance_rate:.0%}"
    return "\n".join(
        [
            f"# Weekly Research Report — {r.period_start} to {r.period_end}",
            "",
            f"> {READ_ONLY_NOTICE}",
            "",
            f"_Generated {r.generated_at.isoformat()} · "
            f"{r.num_trades} trades · {r.num_signals} signals · {r.num_regimes} regime days_",
            "",
            "## Objective metrics",
            "",
            f"- **Expectancy:** {o.expectancy_r:.2f} R",
            f"- **Profit factor:** {_pf(o.profit_factor)}  |  "
            f"**Net P&L:** {r.net_pnl:+,.0f}  |  **Max drawdown:** {r.max_drawdown_r:.2f} R",
            f"- **Avg / largest winner:** {o.avg_winner_r:.2f}R / {o.largest_winner_r:.2f}R  |  "
            f"**Trend capture:** {_opt_pct(o.trend_capture)}",
            f"- _context — win rate {o.win_rate:.0%}, payoff {o.payoff_ratio:.2f}x_",
            "",
            "## What worked",
            "",
            _bullets(r.what_worked),
            "",
            "## What failed",
            "",
            _bullets(r.what_failed),
            "",
            "## Largest winners",
            "",
            _trade_table(r.largest_winners),
            "",
            "## Largest losers",
            "",
            _trade_table(r.largest_losers),
            "",
            "## Market regimes",
            "",
            f"- Distribution: {regimes}",
            f"- Latest: {r.latest_regime or '—'}",
            "",
            "## Signals",
            "",
            f"- By status: {statuses}",
            f"- Risk-gateway acceptance rate: {rate}",
            "",
            "## Potential improvements (hypotheses — NOT auto-applied)",
            "",
            _bullets(r.improvements),
        ]
    )


def _opt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"
