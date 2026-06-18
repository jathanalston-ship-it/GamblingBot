"""Reporting: the automated weekly research system (and, later, tearsheets/plots).

The weekly research reporter (:mod:`momentum.reporting.research_report`) reads
all trades, signals and regimes for a period and emits evidence — what worked,
what failed, largest winners/losers and improvement hypotheses — as markdown,
JSON and a database record. It is strictly read-only and never modifies the
strategy. See docs/RESEARCH_REPORTING.md.
"""

from __future__ import annotations

from momentum.reporting.research_report import (
    READ_ONLY_NOTICE,
    WeeklyResearchReport,
    generate_weekly_report,
    run_weekly_report,
)

__all__ = [
    "WeeklyResearchReport",
    "generate_weekly_report",
    "run_weekly_report",
    "READ_ONLY_NOTICE",
]
