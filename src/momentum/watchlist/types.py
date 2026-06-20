"""Value objects for multi-horizon watchlists.

``WatchlistCandidate`` is the engine input (one scored symbol with its conviction
factors + scan context). ``WatchlistEntry`` is one ranked output row, a frozen
value object with ``to_record`` mapping 1:1 onto the ``watchlist_entries`` table.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskRating(str, Enum):
    """Coarse per-name risk band from expected stop size (ATR-derived)."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    UNKNOWN = "Unknown"


@dataclass(frozen=True, slots=True)
class WatchlistCandidate:
    """A scored symbol fed into the watchlist engine."""

    symbol: str
    base_conviction: float  # the 0-100 conviction score
    band: str | None
    factors: dict[str, float]  # normalized [0,1] factor values, keyed by component name
    sector: str | None = None
    price: float | None = None
    atr: float | None = None  # average true range (daily), same units as price


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    """One ranked watchlist row (persisted verbatim)."""

    horizon: str
    horizon_label: str
    symbol: str
    rank: int
    conviction: float  # horizon-specific conviction (0-100)
    base_conviction: float
    band: str | None
    sector: str | None
    risk_rating: str
    horizon_days: int
    expected_move_pct: float | None
    expected_risk_pct: float | None
    reward_risk: float | None
    as_of: dt.date
    run_id: str | None
    generated_at: dt.datetime
    model_version: str
    config_hash: str | None

    def to_record(self) -> dict[str, Any]:
        """Map to a ``watchlist_entries`` ORM row's kwargs."""
        return {
            "horizon": self.horizon,
            "horizon_label": self.horizon_label,
            "symbol": self.symbol,
            "rank": self.rank,
            "conviction": self.conviction,
            "base_conviction": self.base_conviction,
            "band": self.band,
            "sector": self.sector,
            "risk_rating": self.risk_rating,
            "horizon_days": self.horizon_days,
            "expected_move_pct": self.expected_move_pct,
            "expected_risk_pct": self.expected_risk_pct,
            "reward_risk": self.reward_risk,
            "as_of": self.as_of,
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "model_version": self.model_version,
            "config_hash": self.config_hash,
        }
