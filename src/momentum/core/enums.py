"""Domain enumerations.

The full catalog (per docs/ARCHITECTURE.md) is ``Side``, ``OrderType``,
``TimeInForce``, ``OrderStatus``, ``SignalType``, ``ExitReason``, ``RunMode``,
``RegimeState``, ``AssetClass``. The regime- and risk-related members are
implemented here; the remaining trading-execution members are added by later
phases.

All enums subclass ``str`` so their values serialize transparently to JSON,
YAML and SQL string columns.
"""

from __future__ import annotations

from enum import Enum


class Side(str, Enum):
    """Direction of a position or order."""

    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        """+1 for long, -1 for short — the direction price risk runs."""
        return 1 if self is Side.LONG else -1


class InstrumentType(str, Enum):
    """How a bullish thesis is expressed in the market.

    Chosen by the instrument-selection engine from the trade thesis and market
    context. All are *bullish* expressions with different cost / leverage /
    decay / holding-period trade-offs.
    """

    SHARES = "shares"
    LONG_CALL = "long_call"
    VERTICAL_CALL_SPREAD = "vertical_call_spread"
    LEAPS = "leaps"

    @property
    def is_option(self) -> bool:
        return self is not InstrumentType.SHARES

    @property
    def is_defined_risk(self) -> bool:
        """Whether max loss is capped at entry (true for all long-option structures)."""
        return self is not InstrumentType.SHARES

    @property
    def display(self) -> str:
        return self.value.replace("_", " ").title()


class RiskVerdict(str, Enum):
    """Outcome of the risk gateway for a proposed trade."""

    APPROVE = "approve"
    RESIZE = "resize"
    VETO = "veto"

    @property
    def is_tradeable(self) -> bool:
        """Whether an order may be created (approved or resized, not vetoed)."""
        return self is not RiskVerdict.VETO


class RegimeState(str, Enum):
    """Headline market-regime label.

    The single question the engine answers: *are conditions favorable for
    aggressive momentum trading?*  ``BULLISH`` = yes, ``BEARISH`` = no,
    ``NEUTRAL`` = mixed / reduce risk.
    """

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"

    @property
    def is_favorable(self) -> bool:
        """True only in the regime where aggressive momentum is sanctioned."""
        return self is RegimeState.BULLISH

    @property
    def display(self) -> str:
        """Title-case label for reports (e.g. ``"Bullish"``)."""
        return self.value.capitalize()


class TrendState(str, Enum):
    """Direction component of the regime (benchmark trend structure)."""

    UPTREND = "uptrend"
    SIDEWAYS = "sideways"
    DOWNTREND = "downtrend"


class VolatilityState(str, Enum):
    """Volatility component of the regime (typically driven by the VIX)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"
