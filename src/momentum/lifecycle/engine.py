"""Setup-lifecycle derivation (pure logic).

Maps a candidate's current evidence to exactly one of seven states. The mapping
is a priority cascade: a closed trade is terminal (Completed/Failed); an open
trade is Active (or Extended if crowded); otherwise the pre-trade state comes
from the scan + conviction (Triggered / Ready / Building), with an invalidation
path to Failed when a Ready/Triggered setup loses its gating.
"""

from __future__ import annotations

from momentum.lifecycle.config import LifecycleConfig, default_config
from momentum.lifecycle.types import LifecycleEvaluation, LifecycleInputs, LifecycleState

_TARGET_EXITS = {"target", "target_hit", "take_profit", "profit_target"}


class LifecycleEngine:
    """Derives a :class:`LifecycleState` (+ reason) for one candidate."""

    def __init__(self, config: LifecycleConfig | None = None) -> None:
        self.config = config or default_config()

    def evaluate(self, inputs: LifecycleInputs) -> LifecycleEvaluation:
        state, reason = self._state(inputs)
        return LifecycleEvaluation(symbol=inputs.symbol, state=state, reason=reason)

    def _state(self, x: LifecycleInputs) -> tuple[LifecycleState, str]:
        cfg = self.config

        # 1. Closed trade — terminal.
        if x.closed_trade:
            won = (x.closed_exit_reason or "").lower() in _TARGET_EXITS or (
                x.closed_r is not None and x.closed_r > 0
            )
            if won:
                return LifecycleState.COMPLETED, self._closed_reason("target reached", x.closed_r)
            return LifecycleState.FAILED, self._closed_reason("stopped out", x.closed_r)

        # 2. Open trade — Active, or Extended when the move is crowded.
        if x.open_trade:
            gain, r = self._open_progress(x)
            crowded_r = r is not None and r >= cfg.extended_r
            crowded_gain = gain is not None and gain >= cfg.extended_gain_pct
            climax = (
                x.relative_volume is not None
                and x.relative_volume >= cfg.climax_rvol
                and x.distance_from_ath is not None
                and x.distance_from_ath >= cfg.trigger_ath_distance
            )
            if crowded_r or crowded_gain or climax:
                bits = []
                if r is not None:
                    bits.append(f"+{r:.1f}R")
                if gain is not None:
                    bits.append(f"+{gain * 100:.0f}%")
                if climax:
                    bits.append("climax volume")
                return LifecycleState.EXTENDED, "move extended (" + ", ".join(bits) + ")"
            return LifecycleState.ACTIVE, "trade in progress"

        # 3. No trade — derive the pre-trade state from scan + conviction.
        d_ath = x.distance_from_ath
        if x.has_entry_signal or (
            x.passed_scan and d_ath is not None and d_ath >= cfg.trigger_ath_distance
        ):
            return LifecycleState.TRIGGERED, "entry condition hit (breakout)"

        ready = (
            x.passed_scan
            and (x.conviction_score or 0.0) >= cfg.ready_conviction
            and d_ath is not None
            and d_ath >= cfg.ready_ath_distance
            and (x.relative_volume or 0.0) >= cfg.ready_rvol
        )
        if ready:
            return LifecycleState.READY, "conditions nearly met"

        # Invalidation: a setup that was Ready/Triggered but lost its gating.
        if cfg.invalidate_on_scan_fail and x.prior_state in (
            LifecycleState.READY,
            LifecycleState.TRIGGERED,
        ):
            broke_support = (
                x.price is not None and x.support_level is not None and x.price < x.support_level
            )
            if not x.passed_scan or broke_support:
                why = "lost support" if broke_support else "scan no longer qualifies"
                return LifecycleState.FAILED, f"setup invalidated ({why})"

        return LifecycleState.BUILDING, "setup forming"

    # -- helpers ------------------------------------------------------------- #
    @staticmethod
    def _open_progress(x: LifecycleInputs) -> tuple[float | None, float | None]:
        if x.price is None or x.open_entry_price is None or x.open_entry_price <= 0:
            return None, None
        gain = (x.price - x.open_entry_price) / x.open_entry_price
        r = (
            (x.price - x.open_entry_price) / x.open_risk_per_share
            if x.open_risk_per_share and x.open_risk_per_share > 0
            else None
        )
        return gain, r

    @staticmethod
    def _closed_reason(label: str, r: float | None) -> str:
        return f"{label} ({r:+.1f}R)" if r is not None else label
