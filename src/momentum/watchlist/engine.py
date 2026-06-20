"""Multi-horizon watchlist generation (pure logic).

For each horizon the engine re-weights the candidate's normalized conviction
factors (emphasising the signals that matter on that timeframe), ranks the
universe by the resulting horizon conviction, and keeps the top ``size``. Expected
move / risk / reward:risk are derived from ATR scaled to the horizon. The engine
is a pure function of (candidates, config) -> entries, so it is trivially tested.
"""

from __future__ import annotations

import datetime as dt
import math

from momentum.watchlist.config import HorizonProfile, WatchlistConfig, default_config
from momentum.watchlist.types import RiskRating, WatchlistCandidate, WatchlistEntry


class WatchlistEngine:
    """Turns scored candidates into per-horizon ranked watchlists."""

    def __init__(self, config: WatchlistConfig | None = None) -> None:
        self.config = config or default_config()

    def generate(
        self,
        candidates: list[WatchlistCandidate],
        *,
        as_of: dt.date,
        run_id: str | None = None,
        generated_at: dt.datetime | None = None,
    ) -> dict[str, list[WatchlistEntry]]:
        """Return ``{horizon_key: [entries...]}`` ranked best-first."""
        when = generated_at or dt.datetime.now(dt.timezone.utc)
        cfg_hash = self.config.config_hash()
        out: dict[str, list[WatchlistEntry]] = {}
        for profile in self.config.horizons:
            scored = sorted(
                candidates,
                key=lambda c: self._horizon_conviction(c, profile),
                reverse=True,
            )
            entries: list[WatchlistEntry] = []
            for rank, cand in enumerate(scored[: profile.size], start=1):
                entries.append(self._entry(cand, profile, rank, as_of, run_id, when, cfg_hash))
            out[profile.key] = entries
        return out

    # -- scoring ------------------------------------------------------------- #
    def _horizon_conviction(self, cand: WatchlistCandidate, profile: HorizonProfile) -> float:
        """Re-weight the candidate's normalized factors for this horizon (0-100).

        Weights are renormalized over the factors actually present, so a missing
        factor doesn't silently drag the score down. Falls back to the base
        conviction when no weighted factor is available.
        """
        num = 0.0
        denom = 0.0
        for factor, weight in profile.weights.items():
            value = cand.factors.get(factor)
            if value is None:
                continue
            num += value * weight
            denom += weight
        if denom <= 0:
            return cand.base_conviction
        return round(100.0 * num / denom, 2)

    # -- expected move / risk ------------------------------------------------ #
    def _entry(
        self,
        cand: WatchlistCandidate,
        profile: HorizonProfile,
        rank: int,
        as_of: dt.date,
        run_id: str | None,
        generated_at: dt.datetime,
        cfg_hash: str,
    ) -> WatchlistEntry:
        atr_pct = (
            cand.atr / cand.price
            if cand.atr is not None and cand.price is not None and cand.price > 0
            else None
        )
        expected_risk_pct = (
            round(atr_pct * profile.stop_atr_mult, 4) if atr_pct is not None else None
        )
        expected_move_pct = (
            round(atr_pct * profile.move_sigma * math.sqrt(profile.days), 4)
            if atr_pct is not None
            else None
        )
        reward_risk = (
            round(expected_move_pct / expected_risk_pct, 2)
            if expected_move_pct is not None
            and expected_risk_pct is not None
            and expected_risk_pct > 0
            else None
        )
        return WatchlistEntry(
            horizon=profile.key,
            horizon_label=profile.label,
            symbol=cand.symbol,
            rank=rank,
            conviction=self._horizon_conviction(cand, profile),
            base_conviction=round(cand.base_conviction, 2),
            band=cand.band,
            sector=cand.sector,
            risk_rating=self._risk_rating(expected_risk_pct).value,
            horizon_days=profile.days,
            expected_move_pct=expected_move_pct,
            expected_risk_pct=expected_risk_pct,
            reward_risk=reward_risk,
            as_of=as_of,
            run_id=run_id,
            generated_at=generated_at,
            model_version=self.config.model_version,
            config_hash=cfg_hash,
        )

    def _risk_rating(self, expected_risk_pct: float | None) -> RiskRating:
        if expected_risk_pct is None:
            return RiskRating.UNKNOWN
        if expected_risk_pct <= self.config.risk_low_max_pct:
            return RiskRating.LOW
        if expected_risk_pct <= self.config.risk_medium_max_pct:
            return RiskRating.MEDIUM
        return RiskRating.HIGH
