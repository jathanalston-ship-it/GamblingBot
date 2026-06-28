"""Composable, individually-testable filter primitives.

Each filter is a small callable that takes the scanner's per-symbol **features**
table (one row per symbol, the columns produced by
``MomentumScanner._build_features``) and returns a boolean ``Series`` — ``True``
where the symbol passes. Filters compose with :func:`combine`, which ANDs a list
of them and reports how many symbols each one eliminated (handy for tuning).

Keeping these as data-only column predicates (no bar math, no I/O) is what makes
them trivially unit-testable and reorderable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd


class Filter(Protocol):
    """A named predicate over the features table."""

    @property
    def name(self) -> str: ...

    def __call__(self, features: pd.DataFrame) -> pd.Series: ...


@dataclass(frozen=True)
class MinPrice:
    """Keep symbols whose last price exceeds ``threshold`` (e.g. > $5)."""

    threshold: float
    name: str = "min_price"

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        return features["price"] > self.threshold


@dataclass(frozen=True)
class MinDollarVolume:
    """Keep liquid names: trailing average daily dollar volume >= ``threshold``."""

    threshold: float
    name: str = "min_dollar_volume"

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        return features["dollar_volume"] >= self.threshold


@dataclass(frozen=True)
class MinRelativeVolume:
    """Keep symbols trading at >= ``threshold`` x their normal volume."""

    threshold: float
    name: str = "min_relative_volume"

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        return features["relative_volume"] >= self.threshold


@dataclass(frozen=True)
class WithinDistanceOfATH:
    """Keep symbols within ``max_distance`` (fraction) of their all-time high.

    ``distance_from_ath`` is signed and <= 0 (0 == at the high), so the gate is
    ``distance_from_ath >= -max_distance``.
    """

    max_distance: float
    name: str = "within_ath"

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        return features["distance_from_ath"] >= -abs(self.max_distance)


@dataclass(frozen=True)
class EmaBullishStack:
    """Require an upward EMA stack (fast > mid and/or mid > slow)."""

    require_fast_above_mid: bool = True
    require_mid_above_slow: bool = True
    name: str = "ema_stack"

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        result = pd.Series(True, index=features.index)
        if self.require_fast_above_mid:
            result &= features["ema_fast"] > features["ema_mid"]
        if self.require_mid_above_slow:
            result &= features["ema_mid"] > features["ema_slow"]
        return result


@dataclass(frozen=True)
class MinSectorRelativeStrength:
    """Keep symbols whose sector relative-strength percentile >= ``threshold``."""

    threshold: float
    name: str = "min_sector_rs"

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        rs = features["sector_rs"]
        # symbols with no sector info (NaN) are not excluded by this gate
        return (rs >= self.threshold) | rs.isna()


@dataclass
class FilterReport:
    """Per-filter elimination counts plus the final combined mask.

    ``reasons`` maps each *rejected* symbol to the name of the **first** filter that
    eliminated it (passing symbols are absent), so a scan can persist *why* each
    candidate dropped — not just an aggregate count.
    """

    passed: pd.Series
    eliminated: dict[str, int]
    n_in: int
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def n_out(self) -> int:
        return int(self.passed.sum())


def combine(features: pd.DataFrame, filters: Sequence[Filter]) -> FilterReport:
    """AND a sequence of filters, recording how many each one removes.

    Filters are applied in order against the *surviving* mask, so both ``eliminated``
    (counts) and ``reasons`` (per-symbol) attribute each drop to the first filter
    that rejects it.
    """
    mask = pd.Series(True, index=features.index)
    eliminated: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for filt in filters:
        before = int(mask.sum())
        result = filt(features).reindex(features.index).fillna(False).astype(bool)
        newly_failed = mask & ~result  # passing until now, rejected by this filter
        for symbol in features.index[newly_failed]:
            reasons[str(symbol)] = filt.name
        mask &= result
        eliminated[filt.name] = before - int(mask.sum())
    return FilterReport(passed=mask, eliminated=eliminated, n_in=len(features), reasons=reasons)
