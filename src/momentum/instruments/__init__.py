"""Instrument-selection subsystem.

The strategy emits a *bullish thesis* (symbol, expected move, horizon). This
subsystem decides **how** to express it — shares, long calls, vertical call
spreads or LEAPS — from the thesis and the market context (volatility, implied
volatility, liquidity, risk budget, portfolio exposure). It does not size or
route orders (that stays with risk/execution); it picks the *instrument* and a
suggested structure, with an auditable rationale.

It also hosts the **options-qualification engine**
(:class:`OptionsQualificationEngine`): a hard gate that vets a concrete option
contract (open interest, spread, volume, days to expiry, IV, gamma risk) and
returns a ``QUALIFIED`` / ``REJECTED`` verdict before any option may back a
trade.

See docs/INSTRUMENT_SELECTION.md and docs/OPTIONS_QUALIFICATION.md.
"""

from __future__ import annotations

from momentum.core.enums import InstrumentType, QualificationVerdict
from momentum.instruments.engine import InstrumentSelectionEngine
from momentum.instruments.qualification import (
    GateCheck,
    OptionQuote,
    OptionsQualification,
    OptionsQualificationEngine,
)
from momentum.instruments.qualification_config import OptionsQualificationConfig
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
    # options qualification
    "OptionsQualificationEngine",
    "OptionsQualificationConfig",
    "OptionQuote",
    "OptionsQualification",
    "GateCheck",
    "QualificationVerdict",
]
