"""The momentum scanner: screen the US equity universe and rank candidates.

``MomentumScanner.scan`` takes a mapping of ``symbol -> canonical OHLCV frame``
(as produced by :mod:`momentum.data`), builds a per-symbol **features** table,
applies the configured hard filters, computes a cross-sectional **momentum
score** (0..100), and returns ranked :class:`ScanCandidate` objects.

Pipeline
--------
1. **Features** — per symbol: price, avg dollar volume, relative volume,
   distance from all-time high, 20/50/200 EMAs, ATR, blended momentum, sector.
2. **Score** — blend cross-sectional components (momentum, trend alignment,
   ATH proximity, relative volume, sector relative strength) per the configured
   weights, re-normalized over whichever components are available.
3. **Filter** — price > $5, liquidity, relative volume, within-ATH, EMA stack
   (20>50, 50>200), sector relative strength.
4. **Rank** — survivors ordered by score (rank 1 = strongest).

The result is DataFrame-backed (auditable) and converts straight to ORM rows for
the ``scan_results`` table via :meth:`ScanResult.to_records`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from momentum.signals.indicators import (
    all_time_high,
    atr,
    average_dollar_volume,
    ema,
    relative_volume,
    rolling_high,
    swing_pivot_levels,
)
from momentum.signals.momentum import (
    blended_momentum,
    percentile_rank,
    sector_relative_strength,
)
from momentum.universe.filters import (
    EmaBullishStack,
    Filter,
    FilterReport,
    MinDollarVolume,
    MinPrice,
    MinRelativeVolume,
    MinSectorRelativeStrength,
    WithinDistanceOfATH,
    combine,
)
from momentum.universe.scanner_config import ScannerConfig

# Score component column -> ScoreWeights field it is weighted by.
_COMPONENT_WEIGHTS = {
    "c_momentum": "momentum",
    "c_trend": "trend",
    "c_ath": "ath_proximity",
    "c_rvol": "relative_volume",
    "c_sector": "sector_rs",
}


@dataclass(frozen=True, slots=True)
class ScanCandidate:
    """One ranked symbol with its score and supporting features."""

    symbol: str
    rank: int
    momentum_score: float
    price: float
    volume: float
    dollar_volume: float
    relative_volume: float | None
    distance_from_ath: float
    ema_fast: float
    ema_mid: float
    ema_slow: float
    atr: float | None
    support_level: float | None
    resistance_level: float | None
    sector: str | None
    sector_rs: float | None
    components: dict[str, float]


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Full scan output: every symbol's features plus the ranked survivors."""

    as_of: pd.Timestamp
    features: pd.DataFrame
    filter_report: FilterReport
    model_version: str
    top_n: int | None = None

    @property
    def candidates(self) -> list[ScanCandidate]:
        """Passing symbols, strongest first (capped at ``top_n`` if set)."""
        if "passed" not in self.features.columns or self.features.empty:
            return []
        passed = self.features[self.features["passed"]].sort_values("rank")
        if self.top_n is not None:
            passed = passed.head(self.top_n)
        return [self._to_candidate(sym, row) for sym, row in passed.iterrows()]

    def top(self, n: int) -> list[ScanCandidate]:
        return self.candidates[:n]

    def to_frame(self) -> pd.DataFrame:
        return self.features

    def __len__(self) -> int:
        if "passed" not in self.features.columns:
            return 0
        return int(self.features["passed"].sum())

    @staticmethod
    def _to_candidate(symbol: str, row: pd.Series) -> ScanCandidate:
        components = {
            name: (None if pd.isna(row[name]) else round(float(row[name]), 6))
            for name in _COMPONENT_WEIGHTS
        }
        return ScanCandidate(
            symbol=str(symbol),
            rank=int(row["rank"]),
            momentum_score=round(float(row["momentum_score"]), 4),
            price=float(row["price"]),
            volume=float(row["volume"]),
            dollar_volume=float(row["dollar_volume"]),
            relative_volume=_opt(row["relative_volume"]),
            distance_from_ath=float(row["distance_from_ath"]),
            ema_fast=float(row["ema_fast"]),
            ema_mid=float(row["ema_mid"]),
            ema_slow=float(row["ema_slow"]),
            atr=_opt(row.get("atr")),
            support_level=_opt(row.get("support_level")),
            resistance_level=_opt(row.get("resistance_level")),
            sector=None if pd.isna(row.get("sector")) else str(row["sector"]),
            sector_rs=_opt(row.get("sector_rs")),
            components=components,  # type: ignore[arg-type]
        )

    def to_records(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        """Rows ready for the ``scan_results`` table (passing candidates only)."""
        records = []
        for c in self.candidates:
            records.append(
                {
                    "run_id": run_id,
                    "as_of": self.as_of.date(),
                    "model_version": self.model_version,
                    "symbol": c.symbol,
                    "rank": c.rank,
                    "momentum_score": c.momentum_score,
                    "passed": True,
                    "price": c.price,
                    "dollar_volume": c.dollar_volume,
                    "relative_volume": c.relative_volume,
                    "distance_from_ath": c.distance_from_ath,
                    "ema_fast": c.ema_fast,
                    "ema_mid": c.ema_mid,
                    "ema_slow": c.ema_slow,
                    "atr": c.atr,
                    "support_level": c.support_level,
                    "resistance_level": c.resistance_level,
                    "sector": c.sector,
                    "sector_rs": c.sector_rs,
                    "components": c.components,
                }
            )
        return records


class MomentumScanner:
    """Screens and ranks a universe of symbols by momentum."""

    def __init__(self, config: ScannerConfig | None = None) -> None:
        self.config = config or ScannerConfig()

    # -- public API --------------------------------------------------------- #
    def scan(
        self,
        bars: Mapping[str, pd.DataFrame],
        *,
        sectors: Mapping[str, str] | None = None,
        as_of: Any | None = None,
    ) -> ScanResult:
        """Scan ``bars`` (symbol -> OHLCV) and rank the momentum candidates."""
        as_of_ts = pd.Timestamp(as_of) if as_of is not None else None
        rows: dict[str, dict[str, Any]] = {}
        last_seen: list[pd.Timestamp] = []
        for symbol, frame in bars.items():
            row = self._symbol_features(frame, as_of_ts)
            if row is None:
                continue
            last_seen.append(row.pop("_last_ts"))
            if sectors is not None:
                row["sector"] = sectors.get(symbol)
            rows[symbol.upper()] = row

        if not rows:
            empty = pd.DataFrame()
            ts = as_of_ts or pd.Timestamp.now(tz="UTC")
            return ScanResult(
                ts, empty, FilterReport(pd.Series(dtype=bool), {}, 0), self.config.model_version
            )

        features = pd.DataFrame.from_dict(rows, orient="index")
        if "sector" not in features.columns:
            features["sector"] = pd.NA
        features.index.name = "symbol"

        features = self._score(features)
        report = combine(features, self._filters())
        features["passed"] = report.passed
        features["rank"] = self._rank(features)

        as_of_final = as_of_ts or max(last_seen)
        return ScanResult(
            as_of=as_of_final,
            features=features,
            filter_report=report,
            model_version=self.config.model_version,
            top_n=self.config.top_n,
        )

    # -- feature extraction ------------------------------------------------- #
    def _symbol_features(
        self, frame: pd.DataFrame, as_of: pd.Timestamp | None
    ) -> dict[str, Any] | None:
        cfg = self.config
        if frame is None or frame.empty or "close" not in frame.columns:
            return None
        df = frame
        if as_of is not None:
            df = df.loc[:as_of]
        close = df["close"].dropna()
        if close.empty:
            return None
        high = df["high"] if "high" in df.columns else close
        low = df["low"] if "low" in df.columns else close
        volume = df["volume"] if "volume" in df.columns else pd.Series(0.0, index=df.index)

        ath_series = (
            all_time_high(close)
            if cfg.ath_lookback is None
            else rolling_high(close, cfg.ath_lookback)
        )
        ath = float(ath_series.iloc[-1])
        price = float(close.iloc[-1])
        support_level, resistance_level = swing_pivot_levels(high, low, price, cfg.pivot_window)

        return {
            "price": price,
            "volume": float(volume.iloc[-1]) if len(volume) else float("nan"),
            "dollar_volume": _last(
                average_dollar_volume(close, volume, cfg.dollar_volume_lookback)
            ),
            "relative_volume": _last(relative_volume(volume, cfg.relative_volume_lookback)),
            "ath": ath,
            "distance_from_ath": price / ath - 1.0 if ath > 0 else float("nan"),
            "ema_fast": _last(ema(close, cfg.ema_fast)),
            "ema_mid": _last(ema(close, cfg.ema_mid)),
            "ema_slow": _last(ema(close, cfg.ema_slow)),
            "atr": _last(atr(high, low, close, cfg.atr_period)),
            "support_level": support_level,
            "resistance_level": resistance_level,
            "momentum_raw": blended_momentum(close, cfg.momentum_lookbacks, skip=cfg.momentum_skip),
            "_last_ts": close.index[-1],
        }

    # -- scoring ------------------------------------------------------------ #
    def _score(self, features: pd.DataFrame) -> pd.DataFrame:
        feats = features.copy()
        feats["c_momentum"] = percentile_rank(feats["momentum_raw"])
        feats["c_trend"] = (
            (feats["price"] > feats["ema_fast"]).astype(float)
            + (feats["ema_fast"] > feats["ema_mid"]).astype(float)
            + (feats["ema_mid"] > feats["ema_slow"]).astype(float)
        ) / 3.0
        feats["c_ath"] = (1.0 + feats["distance_from_ath"]).clip(lower=0.0, upper=1.0)
        feats["c_rvol"] = percentile_rank(feats["relative_volume"])
        feats["sector_rs"] = sector_relative_strength(
            feats["momentum_raw"], feats.get("sector", pd.Series(index=feats.index, dtype=object))
        )
        feats["c_sector"] = feats["sector_rs"]

        weights = self.config.weights.as_dict()
        comp_cols = list(_COMPONENT_WEIGHTS)
        w = pd.Series({c: weights[_COMPONENT_WEIGHTS[c]] for c in comp_cols})
        comps = feats[comp_cols]
        numerator = comps.fillna(0.0).mul(w, axis=1).sum(axis=1)
        denominator = comps.notna().mul(w, axis=1).sum(axis=1)
        feats["momentum_score"] = 100.0 * numerator / denominator.replace(0.0, np.nan)
        return feats

    def _rank(self, features: pd.DataFrame) -> pd.Series:
        passed = features["passed"]
        ranks = features["momentum_score"].where(passed).rank(ascending=False, method="first")
        return ranks

    # -- filters ------------------------------------------------------------ #
    def _filters(self) -> list[Filter]:
        f = self.config.filters
        return [
            MinPrice(f.min_price),
            MinDollarVolume(f.min_dollar_volume),
            MinRelativeVolume(f.min_relative_volume),
            WithinDistanceOfATH(f.max_distance_from_ath),
            EmaBullishStack(f.require_ema_fast_above_mid, f.require_ema_mid_above_slow),
            MinSectorRelativeStrength(f.min_sector_rs),
        ]


def _last(series: pd.Series) -> float:
    """Latest non-discarded value of a series, or NaN if empty."""
    return float(series.iloc[-1]) if len(series) else float("nan")


def _opt(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)
