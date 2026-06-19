"""The conviction scoring engine.

Blends eight inputs into a single 0-100 conviction score and a band. Each input
is normalized to [0, 1], weighted, and summed; component contributions add up to
the final score, so every assessment is fully explainable.

Bands (lower-inclusive on the upper boundary):
    LOW      [0, 40)
    MEDIUM   [40, 70)
    HIGH     [70, 85)
    EXTREME  [85, 100]
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from momentum.conviction.config import ConvictionBands, ConvictionConfig, ConvictionNormalization
from momentum.conviction.inputs import ConvictionInputs


class ConvictionBand(str, Enum):
    """Discrete conviction tier."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"

    @classmethod
    def from_score(cls, score: float, bands: ConvictionBands) -> ConvictionBand:
        if score < bands.low_max:
            return cls.LOW
        if score < bands.medium_max:
            return cls.MEDIUM
        if score < bands.high_max:
            return cls.HIGH
        return cls.EXTREME


@dataclass(frozen=True, slots=True)
class ComponentScore:
    """One input's contribution to the conviction score."""

    name: str
    raw: float | None        # the raw input (mapped value for the regime label)
    normalized: float        # mapped to [0, 1]
    weight: float            # configured weight
    contribution: float      # points added to the final 0-100 score

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw": self.raw,
            "normalized": round(self.normalized, 4),
            "weight": self.weight,
            "contribution": round(self.contribution, 4),
        }


@dataclass(frozen=True, slots=True)
class ConvictionResult:
    """The outcome of scoring one setup."""

    score: float
    band: ConvictionBand
    components: tuple[ComponentScore, ...]
    config_hash: str
    model_version: str

    def normalized_map(self) -> dict[str, float]:
        return {c.name: c.normalized for c in self.components}

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "band": self.band.value,
            "config_hash": self.config_hash,
            "model_version": self.model_version,
            "components": [c.to_dict() for c in self.components],
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _linear(value: float | None, lo: float, hi: float, neutral: float) -> float:
    """Linear map ``lo`` -> 0, ``hi`` -> 1 (clamped); missing -> neutral."""
    if value is None:
        return neutral
    if hi <= lo:
        return neutral
    return _clamp((value - lo) / (hi - lo))


def _inverted(value: float | None, max_: float, neutral: float) -> float:
    """Closeness map: 0 -> 1, ``max_`` (or beyond) -> 0; missing -> neutral."""
    if value is None:
        return neutral
    if max_ <= 0:
        return neutral
    return _clamp(1.0 - max(value, 0.0) / max_)


class ConvictionEngine:
    """Turns :class:`ConvictionInputs` into a :class:`ConvictionResult`."""

    def __init__(self, config: ConvictionConfig | None = None) -> None:
        self.config = config or ConvictionConfig()

    def score(self, inputs: ConvictionInputs) -> ConvictionResult:
        n = self.config.normalization
        regime_raw = self._regime_value(inputs.market_regime, n)

        # (name, raw, normalized) for each of the eight inputs.
        normalized: dict[str, float] = {
            "market_regime": regime_raw,
            "sector_strength": _linear(inputs.sector_strength, n.sector_strength_lo, n.sector_strength_hi, n.neutral),
            "relative_volume": _linear(inputs.relative_volume, n.relative_volume_lo, n.relative_volume_hi, n.neutral),
            "distance_to_ath": _inverted(inputs.distance_to_ath, n.distance_to_ath_max, n.neutral),
            "trend_strength": _linear(inputs.trend_strength, n.trend_strength_lo, n.trend_strength_hi, n.neutral),
            "breadth": _linear(inputs.breadth, n.breadth_lo, n.breadth_hi, n.neutral),
            "momentum_score": _linear(inputs.momentum_score, n.momentum_lo, n.momentum_hi, n.neutral),
            "historical_similar_setups": self._historical(inputs, n),
        }
        raws: dict[str, float | None] = {
            "market_regime": regime_raw,
            "sector_strength": inputs.sector_strength,
            "relative_volume": inputs.relative_volume,
            "distance_to_ath": inputs.distance_to_ath,
            "trend_strength": inputs.trend_strength,
            "breadth": inputs.breadth,
            "momentum_score": inputs.momentum_score,
            "historical_similar_setups": inputs.historical_expectancy_r,
        }

        weights = self.config.weights.as_dict()
        total = sum(weights.values())
        components: list[ComponentScore] = []
        score = 0.0
        for name, norm in normalized.items():
            weight = weights[name]
            contribution = (norm * weight / total) * 100.0 if total > 0 else 0.0
            score += contribution
            components.append(ComponentScore(name, raws[name], norm, weight, contribution))

        score = round(score, 2)
        return ConvictionResult(
            score=score,
            band=ConvictionBand.from_score(score, self.config.bands),
            components=tuple(components),
            config_hash=self.config.config_hash(),
            model_version=self.config.model_version,
        )

    @staticmethod
    def _regime_value(label: str | None, n: ConvictionNormalization) -> float:
        if label is None:
            return n.neutral
        return n.regime_map.get(label.lower(), n.neutral)

    @staticmethod
    def _historical(inputs: ConvictionInputs, n: ConvictionNormalization) -> float:
        """Expectancy mapped to [0, 1], shrunk toward neutral for small samples."""
        if inputs.historical_expectancy_r is None or inputs.historical_sample_size <= 0:
            return n.neutral
        raw = _linear(
            inputs.historical_expectancy_r,
            n.historical_expectancy_lo,
            n.historical_expectancy_hi,
            n.neutral,
        )
        confidence = _clamp(inputs.historical_sample_size / n.historical_min_sample)
        return n.neutral + (raw - n.neutral) * confidence
