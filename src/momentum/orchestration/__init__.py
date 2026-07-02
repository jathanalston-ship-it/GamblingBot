"""Orchestration — composes the finished engines into runnable daily flows.

- :class:`DailyPaperPipeline` runs the entry slice (scan → conviction → risk →
  paper order → portfolio → journal) and returns a :class:`PipelineReport`.
- :class:`DailyOrchestrationEngine` runs a full session (recover → exits →
  entries → persist) and is the single source of truth, returning a
  :class:`DailyReport`.
- :class:`Scheduler` is the single entry point that decides whether to run.
- :class:`ExitManager` / :class:`ExitConfig` drive position exits.

See docs/DAILY_PIPELINE.md and docs/ORCHESTRATION.md.
"""

from __future__ import annotations

from momentum.orchestration.daily_report import DailyReport, tally_outcomes
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.exits import (
    ExitConfig,
    ExitManager,
    ExitSignal,
    evaluate_exit,
    trailing_stop,
)
from momentum.orchestration.pipeline import (
    DailyPaperPipeline,
    PipelineReport,
    TradeDecision,
)
from momentum.orchestration.recovery import reconstruct_portfolio
from momentum.orchestration.scheduler import Scheduler

__all__ = [
    "DailyPaperPipeline",
    "PipelineReport",
    "TradeDecision",
    "DailyOrchestrationEngine",
    "DailyReport",
    "tally_outcomes",
    "Scheduler",
    "ExitConfig",
    "ExitManager",
    "ExitSignal",
    "evaluate_exit",
    "trailing_stop",
    "reconstruct_portfolio",
]
