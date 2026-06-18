"""Market-regime engine: is the environment favorable for aggressive momentum?

The strategy is deliberately blind to the macro backdrop; this module is the one
place that decides *when* aggressive momentum entries are sanctioned. It fuses a
handful of independent, well-understood signals into a single auditable verdict:

    Bullish  -> conditions favor aggressive momentum (full risk)
    Neutral  -> mixed; proceed with reduced conviction
    Bearish  -> hostile; stand aside / defensive

Scoring system (transparent and bounded)
-----------------------------------------
Each input is mapped to a sub-score in ``[-1, +1]`` (bearish .. bullish):

* **SPY / QQQ trend** — position of price vs its fast (50) and slow (200) moving
  averages and the 50-vs-200 cross. A clean uptrend scores +1.
* **Market breadth** — a generic advance/decline breadth indicator.
* **New highs / new lows** — the net high-low index ``(NH-NL)/(NH+NL)``.
* **VIX** — *inverted*: calm scores +1, stress scores -1 (low vol favors
  trend-following).
* **50-day participation** — % of the universe above its 50DMA.
* **200-day participation** — % above its 200DMA.

The composite is the weighted mean of the available sub-scores (weights from
config, re-normalized over whatever inputs are present), so the result is always
in ``[-1, +1]``. Two configurable thresholds turn it into the headline label.

The engine consumes the canonical OHLCV frames produced by
:mod:`momentum.data` for SPY/QQQ and plain scalars for the breadth/VIX feeds,
and emits a :class:`RegimeResult` that maps directly onto the ``market_regimes``
table (:meth:`RegimeResult.to_record`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, TypeAlias

import pandas as pd

from momentum.core.enums import RegimeState, TrendState, VolatilityState
from momentum.signals.regime_config import RegimeConfig

CloseInput: TypeAlias = "pd.DataFrame | pd.Series"
ScalarInput: TypeAlias = "float | int | pd.Series | list[float] | tuple[float, ...] | None"


# --------------------------------------------------------------------------- #
# Scoring primitives
# --------------------------------------------------------------------------- #
def linear_score(value: float, low: float, high: float, *, ascending: bool = True) -> float:
    """Map ``value`` to ``[-1, +1]`` linearly between ``low`` and ``high``.

    At/below ``low`` -> -1, at/above ``high`` -> +1 (clamped), midpoint -> 0.
    With ``ascending=False`` the direction is flipped (used for the VIX, where
    *low* is bullish).
    """
    if high == low:
        return 0.0
    t = (value - low) / (high - low)
    t = max(0.0, min(1.0, t))
    score = 2.0 * t - 1.0
    return score if ascending else -score


def high_low_index(new_highs: float, new_lows: float) -> float | None:
    """Net new-high/low index ``(NH-NL)/(NH+NL)`` in ``[-1, +1]``.

    Returns ``None`` when there is no activity (``NH+NL == 0``).
    """
    total = new_highs + new_lows
    if total <= 0:
        return None
    return (new_highs - new_lows) / total


# --------------------------------------------------------------------------- #
# Result objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class FactorScore:
    """One factor's contribution to the verdict."""

    name: str
    score: float  # in [-1, +1]
    weight: float  # normalized weight actually applied
    raw: float | None = None  # the underlying indicator value, for audit

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass(frozen=True, slots=True)
class RegimeResult:
    """The regime verdict plus all supporting evidence."""

    as_of: pd.Timestamp
    state: RegimeState
    score: float  # composite, [-1, +1]
    confidence: float  # [0, 1]
    trend_state: TrendState
    volatility_state: VolatilityState
    factors: tuple[FactorScore, ...]
    benchmark_close: float | None = None
    ma_fast: float | None = None
    ma_slow: float | None = None
    breadth: float | None = None
    model_version: str = "v1"
    benchmark_symbol: str = "SPY"

    @property
    def is_favorable(self) -> bool:
        """Whether aggressive momentum trading is sanctioned (Bullish)."""
        return self.state.is_favorable

    @property
    def factor_map(self) -> dict[str, FactorScore]:
        return {f.name: f for f in self.factors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "state": self.state.value,
            "score": round(self.score, 6),
            "confidence": round(self.confidence, 6),
            "trend_state": self.trend_state.value,
            "volatility_state": self.volatility_state.value,
            "factors": {
                f.name: {
                    "score": round(f.score, 6),
                    "weight": round(f.weight, 6),
                    "raw": f.raw,
                }
                for f in self.factors
            },
        }

    def to_record(self) -> dict[str, Any]:
        """Kwargs matching the ``market_regimes`` ORM columns."""
        return {
            "as_of": self.as_of.date(),
            "benchmark_symbol": self.benchmark_symbol,
            "model_version": self.model_version,
            "regime": self.state.value,
            "trend_state": self.trend_state.value,
            "volatility_state": self.volatility_state.value,
            "score": round(self.score, 6),
            "confidence": round(self.confidence, 6),
            "benchmark_close": self.benchmark_close,
            "ma_fast": self.ma_fast,
            "ma_slow": self.ma_slow,
            "breadth": self.breadth,
            "details": self.to_dict()["factors"],
        }

    def __str__(self) -> str:
        return (
            f"<Regime {self.state.display} score={self.score:+.2f} "
            f"conf={self.confidence:.2f} "
            f"trend={self.trend_state.value} vol={self.volatility_state.value} "
            f"@ {self.as_of.date()}>"
        )


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class RegimeEngine:
    """Classifies the market regime from index trends and breadth/vol feeds."""

    def __init__(self, config: RegimeConfig | None = None) -> None:
        self.config = config or RegimeConfig()

    # -- public API --------------------------------------------------------- #
    def evaluate(
        self,
        spy: CloseInput | None,
        qqq: CloseInput | None = None,
        *,
        vix: ScalarInput = None,
        breadth: ScalarInput = None,
        new_highs: ScalarInput = None,
        new_lows: ScalarInput = None,
        pct_above_50dma: ScalarInput = None,
        pct_above_200dma: ScalarInput = None,
        as_of: Any | None = None,
    ) -> RegimeResult:
        """Classify the regime as of ``as_of`` (default: the last SPY bar).

        ``spy``/``qqq`` are canonical OHLCV frames (or close Series); the rest
        are point-in-time scalars (or Series, of which the last value is used).
        Any input may be omitted — its factor is dropped and the remaining
        weights re-normalized.
        """
        cfg = self.config
        th = cfg.thresholds

        spy_close, spy_fast, spy_slow, ts = self._trend_inputs(spy, as_of)
        qqq_close, qqq_fast, qqq_slow, ts_q = self._trend_inputs(qqq, as_of)
        if ts is None:
            ts = ts_q
        if ts is None:
            ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz="UTC")

        vix_v = _scalar(vix)
        breadth_v = _scalar(breadth)
        nh_v = _scalar(new_highs)
        nl_v = _scalar(new_lows)
        p50_v = _scalar(pct_above_50dma)
        p200_v = _scalar(pct_above_200dma)

        # --- per-factor scores (None => factor absent) -------------------- #
        raw_scores: dict[str, tuple[float, float | None]] = {}

        spy_trend = trend_score(spy_close, spy_fast, spy_slow)
        if spy_trend is not None:
            raw_scores["spy_trend"] = (spy_trend, spy_close)

        qqq_trend = trend_score(qqq_close, qqq_fast, qqq_slow)
        if qqq_trend is not None:
            raw_scores["qqq_trend"] = (qqq_trend, qqq_close)

        if breadth_v is not None:
            raw_scores["breadth"] = (
                linear_score(breadth_v, th.breadth_bear, th.breadth_bull),
                breadth_v,
            )

        if nh_v is not None and nl_v is not None:
            hli = high_low_index(nh_v, nl_v)
            if hli is not None:
                raw_scores["new_high_low"] = (
                    linear_score(hli, th.high_low_bear, th.high_low_bull),
                    hli,
                )

        if vix_v is not None:
            raw_scores["vix"] = (
                linear_score(vix_v, th.vix_calm, th.vix_stress, ascending=False),
                vix_v,
            )

        if p50_v is not None:
            raw_scores["participation_50"] = (
                linear_score(p50_v, th.participation_bear, th.participation_bull),
                p50_v,
            )

        if p200_v is not None:
            raw_scores["participation_200"] = (
                linear_score(p200_v, th.participation_bear, th.participation_bull),
                p200_v,
            )

        factors, composite = self._combine(raw_scores)
        state = self._label(composite)
        trend_state = self._trend_state(factors)
        vol_state = self._volatility_state(vix_v)
        confidence = self._confidence(composite, factors)

        return RegimeResult(
            as_of=ts,
            state=state,
            score=composite,
            confidence=confidence,
            trend_state=trend_state,
            volatility_state=vol_state,
            factors=factors,
            benchmark_close=spy_close,
            ma_fast=spy_fast,
            ma_slow=spy_slow,
            breadth=breadth_v,
            model_version=cfg.model_version,
            benchmark_symbol=cfg.benchmark_symbol,
        )

    # -- internals ---------------------------------------------------------- #
    def _trend_inputs(
        self, bars: CloseInput | None, as_of: Any | None
    ) -> tuple[float | None, float | None, float | None, pd.Timestamp | None]:
        """Extract (close, fast MA, slow MA, timestamp) at ``as_of``."""
        if bars is None:
            return None, None, None, None
        close = _close_series(bars)
        if close.empty:
            return None, None, None, None
        if as_of is not None:
            close = close.loc[: pd.Timestamp(as_of)]
            if close.empty:
                return None, None, None, None
        ts = close.index[-1]
        fast = _last_ma(close, self.config.ma_fast)
        slow = _last_ma(close, self.config.ma_slow)
        return float(close.iloc[-1]), fast, slow, ts

    def _combine(
        self, raw_scores: dict[str, tuple[float, float | None]]
    ) -> tuple[tuple[FactorScore, ...], float]:
        """Weight, normalize and sum the present factors -> composite score."""
        weights = self.config.weights.as_dict()
        present = {name: weights.get(name, 0.0) for name in raw_scores}
        total_w = sum(present.values())
        factors: list[FactorScore] = []
        composite = 0.0
        for name, (score, raw) in raw_scores.items():
            norm_w = present[name] / total_w if total_w > 0 else 0.0
            factors.append(FactorScore(name=name, score=score, weight=norm_w, raw=raw))
            composite += score * norm_w
        # stable, weight-descending order for readable output
        factors.sort(key=lambda f: f.weight, reverse=True)
        return tuple(factors), composite

    def _label(self, composite: float) -> RegimeState:
        th = self.config.thresholds
        if composite >= th.bull_score:
            return RegimeState.BULLISH
        if composite <= th.bear_score:
            return RegimeState.BEARISH
        return RegimeState.NEUTRAL

    def _trend_state(self, factors: tuple[FactorScore, ...]) -> TrendState:
        trend_scores = [f.score for f in factors if f.name in ("spy_trend", "qqq_trend")]
        if not trend_scores:
            return TrendState.SIDEWAYS
        avg = sum(trend_scores) / len(trend_scores)
        th = self.config.thresholds
        if avg >= th.trend_up:
            return TrendState.UPTREND
        if avg <= th.trend_down:
            return TrendState.DOWNTREND
        return TrendState.SIDEWAYS

    def _volatility_state(self, vix: float | None) -> VolatilityState:
        if vix is None:
            return VolatilityState.NORMAL
        th = self.config.thresholds
        if vix < th.vix_low:
            return VolatilityState.LOW
        if vix < th.vix_high:
            return VolatilityState.NORMAL
        if vix < th.vix_extreme:
            return VolatilityState.HIGH
        return VolatilityState.EXTREME

    def _confidence(self, composite: float, factors: tuple[FactorScore, ...]) -> float:
        """Confidence blends signal strength with cross-factor agreement.

        ``strength`` is how far the composite is from zero; ``agreement`` is the
        share of factors pointing the same way as the verdict. A strong score
        backed by aligned factors approaches 1; a weak or conflicted reading
        stays low.
        """
        strength = min(1.0, abs(composite))
        if not factors:
            return 0.0
        if composite == 0:
            agreement = 0.0
        else:
            sign = math.copysign(1.0, composite)
            agreeing = sum(
                1 for f in factors if f.score == 0 or math.copysign(1.0, f.score) == sign
            )
            agreement = agreeing / len(factors)
        return round(0.6 * strength + 0.4 * agreement, 6)


# --------------------------------------------------------------------------- #
# Trend sub-score (module-level so it is independently testable)
# --------------------------------------------------------------------------- #
def trend_score(close: float | None, ma_fast: float | None, ma_slow: float | None) -> float | None:
    """Score an index's trend structure in ``[-1, +1]``.

    Combines three classic, bounded checks (renormalized over whichever MAs are
    available):

    * price vs the slow MA (the 200DMA gate)  — weight 0.5
    * price vs the fast MA (the 50DMA)         — weight 0.3
    * fast MA vs slow MA (golden/death cross)  — weight 0.2

    Returns ``None`` if there is no usable price.
    """
    if close is None or _isnan(close):
        return None
    components: list[tuple[float, float]] = []
    if ma_slow is not None and not _isnan(ma_slow):
        components.append((0.5, 1.0 if close > ma_slow else -1.0))
    if ma_fast is not None and not _isnan(ma_fast):
        components.append((0.3, 1.0 if close > ma_fast else -1.0))
    if ma_fast is not None and ma_slow is not None and not _isnan(ma_fast) and not _isnan(ma_slow):
        components.append((0.2, 1.0 if ma_fast > ma_slow else -1.0))
    if not components:
        return None
    total_w = sum(w for w, _ in components)
    return sum(w * s for w, s in components) / total_w


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _isnan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def _close_series(bars: CloseInput) -> pd.Series:
    if isinstance(bars, pd.Series):
        return bars.dropna()
    if isinstance(bars, pd.DataFrame):
        if "close" in bars.columns:
            return bars["close"].dropna()
        raise ValueError("bars DataFrame must have a 'close' column")
    raise TypeError(f"unsupported bars type: {type(bars)!r}")


def _last_ma(close: pd.Series, period: int) -> float | None:
    if len(close) < period:
        return None
    return float(close.rolling(period).mean().iloc[-1])


def _scalar(value: ScalarInput) -> float | None:
    """Coerce a scalar/Series/sequence input to its latest float, or ``None``."""
    if value is None:
        return None
    if isinstance(value, pd.Series):
        s = value.dropna()
        return float(s.iloc[-1]) if not s.empty else None
    if isinstance(value, (list, tuple)):
        vals = [v for v in value if v is not None and not _isnan(float(v))]
        return float(vals[-1]) if vals else None
    f = float(value)
    return None if _isnan(f) else f
