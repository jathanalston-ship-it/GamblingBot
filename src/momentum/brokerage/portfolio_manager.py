"""Portfolio Manager — the brain that reads the whole book at once.

Pure: positions + account facts (+ optional return series) in, an
explainable :class:`PortfolioAnalysis` out. Computes portfolio exposure,
sector concentration, single-position concentration, average pairwise
correlation, portfolio beta (vs a benchmark series), cash allocation, open
risk, expected downside and capital efficiency — then turns the measurements
into concrete, justified suggestions (Increase / Reduce / Close / Add /
Diversify). No black boxes: every suggestion quotes the number that
triggered it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PositionFacts:
    """What the manager needs to know about one open position."""

    symbol: str
    market_value: float
    sector: str | None = None
    stop_distance_value: float | None = None  # $ at risk to the stop (>= 0)
    health: str | None = None  # Strong | Stable | Weakening | Broken (if tracked)
    returns: tuple[float, ...] = ()  # recent daily returns (for corr/beta)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One concrete portfolio action with its measurable justification."""

    action: str  # increase | reduce | close | add | diversify
    symbol: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "symbol": self.symbol, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PortfolioAnalysis:
    """The full portfolio picture + suggestions."""

    equity: float
    cash: float
    exposure_value: float
    exposure_pct: float
    cash_pct: float
    num_positions: int
    max_position_symbol: str | None
    max_position_pct: float
    max_sector: str | None
    max_sector_pct: float
    avg_pairwise_correlation: float | None
    portfolio_beta: float | None
    open_risk: float
    open_risk_pct: float
    expected_downside: float
    expected_downside_pct: float
    capital_efficiency: float | None
    suggestions: tuple[Suggestion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "exposure_value": round(self.exposure_value, 2),
            "exposure_pct": round(self.exposure_pct, 4),
            "cash_pct": round(self.cash_pct, 4),
            "num_positions": self.num_positions,
            "max_position_symbol": self.max_position_symbol,
            "max_position_pct": round(self.max_position_pct, 4),
            "max_sector": self.max_sector,
            "max_sector_pct": round(self.max_sector_pct, 4),
            "avg_pairwise_correlation": (
                round(self.avg_pairwise_correlation, 3)
                if self.avg_pairwise_correlation is not None
                else None
            ),
            "portfolio_beta": (
                round(self.portfolio_beta, 3) if self.portfolio_beta is not None else None
            ),
            "open_risk": round(self.open_risk, 2),
            "open_risk_pct": round(self.open_risk_pct, 4),
            "expected_downside": round(self.expected_downside, 2),
            "expected_downside_pct": round(self.expected_downside_pct, 4),
            "capital_efficiency": (
                round(self.capital_efficiency, 3) if self.capital_efficiency is not None else None
            ),
            "suggestions": [s.to_dict() for s in self.suggestions],
        }


# Thresholds (module constants; the analysis quotes them in its reasons).
MAX_SINGLE_POSITION_PCT = 0.25
MAX_SECTOR_PCT = 0.50
MIN_SECTOR_POSITIONS = 3
HIGH_CORRELATION = 0.70
UNDERINVESTED_CASH_PCT = 0.70
STOPLESS_DOWNSIDE_PCT = 0.10  # assumed loss on a position with no stop


def _correlation(a: tuple[float, ...], b: tuple[float, ...]) -> float | None:
    n = min(len(a), len(b))
    if n < 10:
        return None
    xs, ys = a[-n:], b[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def _beta(position_returns: tuple[float, ...], benchmark: tuple[float, ...]) -> float | None:
    n = min(len(position_returns), len(benchmark))
    if n < 10:
        return None
    xs, ys = benchmark[-n:], position_returns[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    return cov / var


def analyze_portfolio(
    *,
    equity: float,
    cash: float,
    positions: list[PositionFacts],
    benchmark_returns: tuple[float, ...] = (),
    regime: str | None = None,
) -> PortfolioAnalysis:
    """The whole-book read (pure, total)."""
    exposure = sum(p.market_value for p in positions)
    exposure_pct = exposure / equity if equity > 0 else 0.0
    cash_pct = cash / equity if equity > 0 else 0.0

    # Concentration.
    max_symbol: str | None = None
    max_position_pct = 0.0
    for p in positions:
        share = p.market_value / equity if equity > 0 else 0.0
        if share > max_position_pct:
            max_symbol, max_position_pct = p.symbol, share
    sector_values: dict[str, float] = {}
    sector_counts = Counter[str]()
    for p in positions:
        if p.sector:
            sector_values[p.sector] = sector_values.get(p.sector, 0.0) + p.market_value
            sector_counts[p.sector] += 1
    max_sector: str | None = None
    max_sector_pct = 0.0
    if sector_values and exposure > 0:
        max_sector = max(sector_values, key=lambda s: sector_values[s])
        max_sector_pct = sector_values[max_sector] / exposure

    # Correlation (average pairwise over positions with return series).
    with_returns = [p for p in positions if len(p.returns) >= 10]
    pair_corrs: list[float] = []
    for i in range(len(with_returns)):
        for j in range(i + 1, len(with_returns)):
            corr = _correlation(with_returns[i].returns, with_returns[j].returns)
            if corr is not None:
                pair_corrs.append(corr)
    avg_corr = sum(pair_corrs) / len(pair_corrs) if pair_corrs else None

    # Beta: value-weighted position betas vs the benchmark.
    beta: float | None = None
    if benchmark_returns and exposure > 0:
        weighted = 0.0
        covered = 0.0
        for p in with_returns:
            b = _beta(p.returns, benchmark_returns)
            if b is not None:
                weighted += b * p.market_value
                covered += p.market_value
        beta = weighted / covered if covered > 0 else None

    # Risk.
    open_risk = sum(p.stop_distance_value or 0.0 for p in positions)
    expected_downside = sum(
        p.stop_distance_value
        if p.stop_distance_value is not None
        else p.market_value * STOPLESS_DOWNSIDE_PCT
        for p in positions
    )
    # Capital efficiency: how much of the deployed capital carries a defined
    # edge (risk-managed) — deployed $ per $ of defined risk.
    capital_efficiency = exposure / open_risk if open_risk > 0 else None

    suggestions = _suggest(
        positions=positions,
        equity=equity,
        cash_pct=cash_pct,
        max_symbol=max_symbol,
        max_position_pct=max_position_pct,
        max_sector=max_sector,
        max_sector_pct=max_sector_pct,
        sector_counts=sector_counts,
        avg_corr=avg_corr,
        regime=regime,
    )

    return PortfolioAnalysis(
        equity=equity,
        cash=cash,
        exposure_value=exposure,
        exposure_pct=exposure_pct,
        cash_pct=cash_pct,
        num_positions=len(positions),
        max_position_symbol=max_symbol,
        max_position_pct=max_position_pct,
        max_sector=max_sector,
        max_sector_pct=max_sector_pct,
        avg_pairwise_correlation=avg_corr,
        portfolio_beta=beta,
        open_risk=open_risk,
        open_risk_pct=open_risk / equity if equity > 0 else 0.0,
        expected_downside=expected_downside,
        expected_downside_pct=expected_downside / equity if equity > 0 else 0.0,
        capital_efficiency=capital_efficiency,
        suggestions=tuple(suggestions),
    )


def _suggest(
    *,
    positions: list[PositionFacts],
    equity: float,
    cash_pct: float,
    max_symbol: str | None,
    max_position_pct: float,
    max_sector: str | None,
    max_sector_pct: float,
    sector_counts: Counter[str],
    avg_corr: float | None,
    regime: str | None,
) -> list[Suggestion]:
    out: list[Suggestion] = []

    for p in positions:
        if p.health == "Broken":
            out.append(
                Suggestion(
                    "close",
                    p.symbol,
                    f"{p.symbol}'s thesis is graded Broken — the reason for holding is gone.",
                )
            )
        elif p.health == "Weakening":
            out.append(
                Suggestion(
                    "reduce",
                    p.symbol,
                    f"{p.symbol}'s thesis is Weakening — trim while the exit is orderly.",
                )
            )

    if max_symbol is not None and max_position_pct > MAX_SINGLE_POSITION_PCT:
        out.append(
            Suggestion(
                "reduce",
                max_symbol,
                f"{max_symbol} is {max_position_pct:.0%} of equity "
                f"(cap {MAX_SINGLE_POSITION_PCT:.0%}) — single-name risk dominates the book.",
            )
        )

    if (
        max_sector is not None
        and max_sector_pct > MAX_SECTOR_PCT
        and sector_counts[max_sector] >= MIN_SECTOR_POSITIONS
    ):
        out.append(
            Suggestion(
                "diversify",
                None,
                f"{sector_counts[max_sector]} positions put {max_sector_pct:.0%} of exposure in "
                f"{max_sector} (cap {MAX_SECTOR_PCT:.0%}) — they will move together.",
            )
        )

    if avg_corr is not None and avg_corr > HIGH_CORRELATION:
        out.append(
            Suggestion(
                "diversify",
                None,
                f"average pairwise correlation is {avg_corr:.2f} "
                f"(> {HIGH_CORRELATION:.2f}) — the book behaves like one big trade.",
            )
        )

    if cash_pct > UNDERINVESTED_CASH_PCT and regime == "bullish":
        out.append(
            Suggestion(
                "add",
                None,
                f"{cash_pct:.0%} cash in a bullish regime — capital is idle while "
                "conditions favor momentum entries.",
            )
        )

    strong = [p for p in positions if p.health == "Strong"]
    if strong and equity > 0:
        smallest = min(strong, key=lambda p: p.market_value)
        share = smallest.market_value / equity
        if share < 0.05:
            out.append(
                Suggestion(
                    "increase",
                    smallest.symbol,
                    f"{smallest.symbol} is graded Strong but only {share:.1%} of equity — "
                    "the best thesis carries the least capital.",
                )
            )

    return out
