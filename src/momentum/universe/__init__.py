"""Tradeable-universe construction & momentum scanning.

The momentum scanner (:class:`~momentum.universe.screener.MomentumScanner`)
screens the US equity universe and ranks candidates by a composite momentum
score. Filter primitives live in :mod:`momentum.universe.filters`; tunables in
:mod:`momentum.universe.scanner_config`.

See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""

from __future__ import annotations

from momentum.universe.filters import (
    EmaBullishStack,
    Filter,
    FilterReport,
    MinDollarVolume,
    MinPrice,
    MinRelativeVolume,
    MinSectorRelativeStrength,
    WithinDistanceOfATH,
    combine,
)
from momentum.universe.scanner_config import ScanFilters, ScannerConfig, ScoreWeights
from momentum.universe.screener import MomentumScanner, ScanCandidate, ScanResult

__all__ = [
    "MomentumScanner",
    "ScanResult",
    "ScanCandidate",
    "ScannerConfig",
    "ScanFilters",
    "ScoreWeights",
    # filter primitives
    "Filter",
    "FilterReport",
    "MinPrice",
    "MinDollarVolume",
    "MinRelativeVolume",
    "WithinDistanceOfATH",
    "EmaBullishStack",
    "MinSectorRelativeStrength",
    "combine",
]
