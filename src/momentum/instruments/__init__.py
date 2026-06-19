"""Instrument-selection subsystem.

The strategy emits a *bullish thesis* (symbol, expected move, horizon). This
subsystem decides **how** to express it — shares, long calls, vertical call
spreads or LEAPS — from the thesis and the market context (volatility, implied
volatility, liquidity, risk budget, portfolio exposure). It does not size or
route orders (that stays with risk/execution); it picks the *instrument* and a
suggested structure, with an auditable rationale.

See docs/INSTRUMENT_SELECTION.md.
"""

from __future__ import annotations

from momentum.core.enums import InstrumentType
from momentum.instruments.engine import InstrumentSelectionEngine
from momentum.instruments.selection_config import InstrumentSelectionConfig
from momentum.instruments.types import (
    CandidateScore,
    InstrumentContext,
    InstrumentDecision,
    InstrumentStructure,
    TradeThesis,
)

__all__ = [
    "InstrumentSelectionEngine",
    "InstrumentSelectionConfig",
    "TradeThesis",
    "InstrumentContext",
    "InstrumentDecision",
    "InstrumentStructure",
    "CandidateScore",
    "InstrumentType",
]
