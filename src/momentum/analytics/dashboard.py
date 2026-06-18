"""Render trade-intelligence reports as text/markdown dashboards.

Dependency-free (no plotting libs) so dashboards render anywhere — terminal,
markdown file, PR comment, notebook. Each panel leads with the objective metrics
(expectancy, profit factor, trend capture); win rate appears only as context.
A richer Plotly tearsheet can sit on top of the same report later.
"""

from __future__ import annotations

from momentum.analytics.attribution import TradeIntelligenceReport
from momentum.analytics.trade_analysis import TradeStats

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("trades", "num_trades"),
    ("expectancy_R", "expectancy_r"),
    ("profit_factor", "profit_factor"),
    ("avg_winner_R", "avg_winner_r"),
    ("trend_capture", "trend_capture"),
    ("win_rate", "win_rate"),
)


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "—"
    if value == float("inf"):
        return "∞"
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}"


def _row(name: str, stats: TradeStats) -> str:
    cells = [name]
    for _, attr in _COLUMNS:
        cells.append(_fmt(getattr(stats, attr)))
    return "| " + " | ".join(cells) + " |"


def _table(title: str, groups: dict[str, TradeStats]) -> str:
    header = "| " + " | ".join([title, *[c for c, _ in _COLUMNS]]) + " |"
    sep = "|" + "|".join(["---"] * (len(_COLUMNS) + 1)) + "|"
    lines = [header, sep]
    if not groups:
        lines.append("| _(no data)_ |" + " |" * len(_COLUMNS))
    else:
        lines.extend(_row(name, stats) for name, stats in groups.items())
    return "\n".join(lines)


def render_dashboard(report: TradeIntelligenceReport, *, title: str = "Trade Intelligence") -> str:
    """Render the full attribution report as a markdown dashboard."""
    o = report.overall
    sections = [
        f"# {title}",
        "",
        "## Objective (what we optimise for)",
        "",
        f"- **Expectancy:** {_fmt(o.expectancy_r)} R  (${o.expectancy_dollars:,.0f}/trade)",
        f"- **Profit factor:** {_fmt(o.profit_factor)}",
        f"- **Average winner:** {_fmt(o.avg_winner_r)} R  |  "
        f"**Largest winner:** {_fmt(o.largest_winner_r)} R",
        f"- **Trend capture:** {_fmt(o.trend_capture)}  |  "
        f"**Payoff asymmetry:** {_fmt(o.payoff_ratio)}x",
        f"- _context — win rate {o.win_rate:.0%}, {o.num_trades} trades, "
        f"winners held {o.winner_loser_hold_ratio:.1f}x longer than losers_",
        "",
        "## By sector",
        "",
        _table("sector", report.by_sector),
        "",
        "## By market regime",
        "",
        _table("regime", report.by_regime),
        "",
        "## By entry reason",
        "",
        _table("entry_reason", report.by_entry_reason),
        "",
        "## By exit reason",
        "",
        _table("exit_reason", report.by_exit_reason),
        "",
        "## By holding period",
        "",
        _table("holding", report.by_holding_bucket),
    ]
    return "\n".join(sections)
