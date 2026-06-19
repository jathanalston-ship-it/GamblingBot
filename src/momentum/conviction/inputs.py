"""The eight conviction inputs and a builder from the platform's own models.

Every field is optional: a missing input contributes a *neutral* score rather
than zero, so partial evidence neither inflates nor unfairly tanks conviction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from momentum.conviction.similar_setups import SimilarSetupStats
    from momentum.persistence.models.market_regime import MarketRegime
    from momentum.persistence.models.scan_result import ScanResult


@dataclass(frozen=True, slots=True)
class ConvictionInputs:
    """Raw inputs for one conviction assessment (all optional)."""

    market_regime: str | None = None  # "bull" | "neutral" | "bear"
    sector_strength: float | None = None  # sector relative-strength percentile, 0..1
    relative_volume: float | None = None  # volume vs trailing average (1.0 = average)
    distance_to_ath: float | None = None  # fractional gap below the all-time high (>= 0)
    trend_strength: float | None = None  # ADX (or equivalent trend-strength reading)
    breadth: float | None = None  # fraction of the market above its 200DMA, 0..1
    momentum_score: float | None = None  # the scanner's momentum score, 0..1
    historical_expectancy_r: float | None = None  # mean R of similar past setups
    historical_sample_size: int = 0  # how many similar setups backed that expectancy

    @classmethod
    def from_sources(
        cls,
        scan: ScanResult,
        regime: MarketRegime | None = None,
        similar: SimilarSetupStats | None = None,
    ) -> ConvictionInputs:
        """Assemble inputs from a scan result, the prevailing regime and history.

        ``trend_strength`` falls back to the regime's ADX (an index-level proxy)
        when a per-symbol reading is unavailable.
        """
        dist = scan.distance_from_ath
        return cls(
            market_regime=regime.regime if regime is not None else None,
            sector_strength=scan.sector_rs,
            relative_volume=scan.relative_volume,
            distance_to_ath=abs(dist) if dist is not None else None,
            trend_strength=(regime.adx if regime is not None else None),
            breadth=(regime.breadth if regime is not None else None),
            momentum_score=scan.momentum_score,
            historical_expectancy_r=similar.expectancy_r if similar is not None else None,
            historical_sample_size=similar.sample_size if similar is not None else 0,
        )
