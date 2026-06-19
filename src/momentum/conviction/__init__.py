"""Conviction scoring engine.

Scores every candidate trade 0-100 from eight inputs — market regime, sector
strength, relative volume, distance to ATH, trend strength, breadth, momentum
score and historical similar setups — and assigns a band (LOW / MEDIUM / HIGH /
EXTREME). Fully explainable (per-component contributions) and persisted to the
``conviction_scores`` table. See docs/CONVICTION.md.
"""
from __future__ import annotations

from momentum.conviction.config import (
    ConvictionBands,
    ConvictionConfig,
    ConvictionNormalization,
    ConvictionWeights,
)
from momentum.conviction.engine import (
    ComponentScore,
    ConvictionBand,
    ConvictionEngine,
    ConvictionResult,
)
from momentum.conviction.inputs import ConvictionInputs
from momentum.conviction.similar_setups import (
    SimilarSetupAnalyzer,
    SimilarSetupStats,
    summarize,
)

__all__ = [
    "ConvictionConfig",
    "ConvictionWeights",
    "ConvictionNormalization",
    "ConvictionBands",
    "ConvictionEngine",
    "ConvictionResult",
    "ConvictionBand",
    "ComponentScore",
    "ConvictionInputs",
    "SimilarSetupAnalyzer",
    "SimilarSetupStats",
    "summarize",
]
