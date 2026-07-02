"""Reporting: the automated weekly research system + per-run HTML tearsheets.

The weekly research reporter (:mod:`momentum.reporting.research_report`) reads
all trades, signals and regimes for a period and emits evidence — what worked,
what failed, largest winners/losers and improvement hypotheses — as markdown,
JSON and a database record. It is strictly read-only and never modifies the
strategy. See docs/RESEARCH_REPORTING.md.

The tearsheet stack (:mod:`plots` → :mod:`tearsheet` → :mod:`report_generator`)
renders a backtest's equity curve + closed trades into one self-contained HTML
document (equity, drawdown, R-distribution, rolling expectancy + headline
metrics), stamped with run id and package version.
"""

from __future__ import annotations

from momentum.reporting.report_generator import generate_report
from momentum.reporting.research_report import (
    READ_ONLY_NOTICE,
    WeeklyResearchReport,
    generate_weekly_report,
    run_weekly_report,
)
from momentum.reporting.tearsheet import build_tearsheet, headline_metrics

__all__ = [
    "WeeklyResearchReport",
    "generate_weekly_report",
    "run_weekly_report",
    "READ_ONLY_NOTICE",
    "build_tearsheet",
    "headline_metrics",
    "generate_report",
]
