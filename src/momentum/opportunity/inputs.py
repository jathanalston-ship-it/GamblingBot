"""The six Home-Run-opportunity inputs and a builder from the platform's models.

The engine asks one question: *could this trade produce an outsized, positive-skew
winner?* The signature of such setups is a fresh **new all-time high** (blue-sky
breakout, no overhead supply) confirmed by **relative volume**, in a **leading
sector**, a favourable **market regime**, with strong **momentum**, and backed by
**historical analogs** that actually paid off big.

Every field is optional: a missing input contributes a *neutral* score (it never
inflates the opportunity) and, for the gated Home-Run tier, an unconfirmed input
fails the gate rather than passing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from momentum.conviction.similar_setups import SimilarSetupStats
    from momentum.persistence.models.market_regime import MarketRegime
    from momentum.persistence.models.scan_result import ScanResult


@dataclass(frozen=True, slots=True)
class OpportunityInputs:
    """Raw inputs for one Home-Run-opportunity classification (all optional).

    The six task inputs map as: **New ATH** -> ``new_ath`` (+ ``distance_to_ath``
    for partial credit when merely near the high); **Relative Volume** ->
    ``relative_volume``; **Sector Leadership** -> ``sector_leadership``; **Market
    Regime** -> ``market_regime``; **Momentum** -> ``momentum_score``;
    **Historical Analogs** -> ``historical_expectancy_r`` (+ ``historical_sample_size``).
    """

    market_regime: str | None = None  # "bull" | "neutral" | "bear"
    new_ath: bool = False  # making a fresh all-time high now
    distance_to_ath: float | None = None  # fractional gap below the ATH (>= 0)
    relative_volume: float | None = None  # volume vs trailing average (1.0 = average)
    sector_leadership: float | None = None  # sector relative-strength percentile, 0..1
    momentum_score: float | None = None  # the scanner's momentum score, 0..1
    historical_expectancy_r: float | None = None  # mean R of similar past setups
    historical_sample_size: int = 0  # how many analogs backed that expectancy

    @classmethod
    def from_sources(
        cls,
        scan: ScanResult,
        regime: MarketRegime | None = None,
        similar: SimilarSetupStats | None = None,
        *,
        new_ath_tolerance: float = 0.0,
    ) -> OpportunityInputs:
        """Assemble inputs from a scan result, the prevailing regime and history.

        ``new_ath`` is inferred from the scan's distance to the all-time high: a
        gap within ``new_ath_tolerance`` (default: exactly at/through the high) is
        treated as a fresh breakout.
        """
        dist = scan.distance_from_ath
        abs_dist = abs(dist) if dist is not None else None
        return cls(
            market_regime=regime.regime if regime is not None else None,
            new_ath=abs_dist is not None and abs_dist <= new_ath_tolerance,
            distance_to_ath=abs_dist,
            relative_volume=scan.relative_volume,
            sector_leadership=scan.sector_rs,
            momentum_score=scan.momentum_score,
            historical_expectancy_r=similar.expectancy_r if similar is not None else None,
            historical_sample_size=similar.sample_size if similar is not None else 0,
        )
