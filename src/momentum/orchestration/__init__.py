"""Pipeline wiring — composes the finished engines into runnable flows.

:class:`DailyPaperPipeline` runs the paper vertical slice (scan -> conviction ->
risk -> paper order -> portfolio -> journal) and returns a
:class:`PipelineReport` of per-candidate :class:`TradeDecision` outcomes.
See docs/DAILY_PIPELINE.md.
"""

from __future__ import annotations

from momentum.orchestration.pipeline import (
    DailyPaperPipeline,
    PipelineReport,
    TradeDecision,
)

__all__ = [
    "DailyPaperPipeline",
    "PipelineReport",
    "TradeDecision",
]
