"""Domain enumerations.

The full catalog (per docs/ARCHITECTURE.md) is ``Side``, ``OrderType``,
``TimeInForce``, ``OrderStatus``, ``SignalType``, ``ExitReason``, ``RunMode``,
``RegimeState``, ``AssetClass``. The regime-related members are implemented
here (used by the market-regime engine and the ``market_regimes`` table);
the trading-execution members are added by later phases.

All enums subclass ``str`` so their values serialize transparently to JSON,
YAML and SQL string columns.
"""

from __future__ import annotations

from enum import Enum


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
