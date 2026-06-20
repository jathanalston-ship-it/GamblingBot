"""Signal evaluation: track every signal's outcome and grade signal quality.

Joins each generated signal to its realised outcome (the trade it produced) and
its predictions (conviction + expected move), then computes calibration,
signal-quality and conviction-accuracy metrics. Pure engine; no new persistence.
"""

from __future__ import annotations

from momentum.signaleval.engine import evaluate, quality
from momentum.signaleval.types import (
    CalibrationBucket,
    ConvictionAccuracy,
    EvaluatedSignal,
    MoveAccuracy,
    SignalEvaluationReport,
    SignalQuality,
)

__all__ = [
    "CalibrationBucket",
    "ConvictionAccuracy",
    "EvaluatedSignal",
    "MoveAccuracy",
    "SignalEvaluationReport",
    "SignalQuality",
    "evaluate",
    "quality",
]
