"""Historical similar-setups analysis.

Answers the eighth conviction input: "when we have taken setups like this before,
how did they pay off?" Looks at closed trades matching a setup's regime / sector
(optionally symbol) and summarizes their realized edge in R, with the sample size
so the engine can shrink low-evidence reads toward neutral.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.trades import TradeRepository


@dataclass(frozen=True, slots=True)
class SimilarSetupStats:
    """Realized performance of historically similar setups."""

    sample_size: int
    expectancy_r: float | None  # mean R per trade (None when no samples)
    win_rate: float | None  # fraction with R > 0
    avg_winner_r: float | None
    avg_loser_r: float | None

    @classmethod
    def empty(cls) -> SimilarSetupStats:
        return cls(0, None, None, None, None)


class SimilarSetupAnalyzer:
    """Computes :class:`SimilarSetupStats` from the closed-trade history."""

    def __init__(self, session: Session) -> None:
        self._trades = TradeRepository(session)

    def analyze(
        self,
        *,
        regime: str | None = None,
        sector: str | None = None,
        symbol: str | None = None,
        run_id: str | None = None,
    ) -> SimilarSetupStats:
        """Summarize closed trades matching the given setup characteristics."""
        candidates = self._trades.closed(run_id)
        matched = [
            t
            for t in candidates
            if t.r_multiple is not None
            and (regime is None or t.regime_label == regime)
            and (sector is None or t.sector == sector)
            and (symbol is None or t.symbol == symbol.upper())
        ]
        return summarize(matched)


def summarize(trades: list[Trade]) -> SimilarSetupStats:
    """Reduce a list of closed trades to :class:`SimilarSetupStats`."""
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    if not rs:
        return SimilarSetupStats.empty()
    winners = [r for r in rs if r > 0]
    losers = [r for r in rs if r <= 0]
    return SimilarSetupStats(
        sample_size=len(rs),
        expectancy_r=sum(rs) / len(rs),
        win_rate=len(winners) / len(rs),
        avg_winner_r=(sum(winners) / len(winners)) if winners else None,
        avg_loser_r=(sum(losers) / len(losers)) if losers else None,
    )
