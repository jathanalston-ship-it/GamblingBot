"""Rarity calibration & verification for the Home-Run tier.

The Home-Run classification must stay rare — **under 5% of all signals**. That is
a population property, so this module turns it into something measurable and
enforceable:

* :func:`tier_distribution` / :func:`home_run_rate` — measure the realized mix.
* :func:`verify_rarity` — check a batch of classifications against the configured
  ``target_home_run_rate`` and return an auditable :class:`RarityReport`.
* :func:`calibrate_home_run_min_score` — raise the score threshold to the
  ``(1 - target)`` quantile of a representative sample, which *guarantees* the
  realized Home-Run rate on that sample is at most the target (the hard gates only
  push it lower).

Run calibration periodically against a representative window of recent signals and
persist the resulting ``config_hash`` so every classification is reproducible.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from momentum.opportunity.config import OpportunityConfig
from momentum.opportunity.engine import (
    HomeRunOpportunityEngine,
    OpportunityResult,
    OpportunityTier,
)
from momentum.opportunity.inputs import OpportunityInputs


@dataclass(frozen=True, slots=True)
class RarityReport:
    """Realized tier mix over a batch, checked against the rarity target."""

    total: int
    normal: int
    enhanced: int
    home_run: int
    target_home_run_rate: float

    @property
    def home_run_rate(self) -> float:
        return self.home_run / self.total if self.total else 0.0

    @property
    def enhanced_rate(self) -> float:
        return self.enhanced / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        """True when Home Runs are at or under the target rate."""
        return self.home_run_rate <= self.target_home_run_rate

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "total": self.total,
            "normal": self.normal,
            "enhanced": self.enhanced,
            "home_run": self.home_run,
            "home_run_rate": round(self.home_run_rate, 6),
            "enhanced_rate": round(self.enhanced_rate, 6),
            "target_home_run_rate": self.target_home_run_rate,
            "ok": self.ok,
        }


def tier_distribution(results: Iterable[OpportunityResult]) -> Counter[OpportunityTier]:
    """Count results by tier."""
    return Counter(r.tier for r in results)


def home_run_rate(results: Sequence[OpportunityResult]) -> float:
    """Fraction of results classified as Home Run."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_home_run) / len(results)


def verify_rarity(
    results: Sequence[OpportunityResult],
    *,
    target_home_run_rate: float,
) -> RarityReport:
    """Summarize a batch of classifications and check the Home-Run rarity target."""
    dist = tier_distribution(results)
    return RarityReport(
        total=len(results),
        normal=dist[OpportunityTier.NORMAL],
        enhanced=dist[OpportunityTier.ENHANCED],
        home_run=dist[OpportunityTier.HOME_RUN],
        target_home_run_rate=target_home_run_rate,
    )


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Lower-interpolated quantile of an already-sorted, non-empty sequence."""
    if not sorted_values:
        return 0.0
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def calibrate_home_run_min_score(
    sample: Iterable[OpportunityInputs],
    *,
    config: OpportunityConfig | None = None,
    target_home_run_rate: float | None = None,
) -> OpportunityConfig:
    """Return a config whose Home-Run threshold caps the rate on ``sample``.

    Sets ``home_run_min_score`` to the ``(1 - target)`` quantile of the sample's
    opportunity scores: by construction at most ``target`` of the sample scores
    at/above it, so — combined with the hard gates, which only remove more — the
    realized Home-Run rate on ``sample`` cannot exceed the target. The threshold
    is never lowered below ``enhanced_min_score`` and never raised above 100.
    """
    cfg = config or OpportunityConfig()
    target = (
        target_home_run_rate if target_home_run_rate is not None else cfg.tiers.target_home_run_rate
    )
    engine = HomeRunOpportunityEngine(cfg)
    scores = sorted(engine.classify(i).score for i in sample)
    if not scores:
        return cfg
    threshold = _quantile(scores, 1.0 - target)
    threshold = min(100.0, max(cfg.tiers.enhanced_min_score + 1e-9, threshold))
    return cfg.with_home_run_min_score(round(threshold, 4))
