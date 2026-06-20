"""Trade-plan generation (pure logic).

Derives a complete plan from a candidate's price, ATR, swing-pivot support /
resistance (EMA fallback), historical analogs, volatility and the market regime:

* **Stop** — the wider of an ATR stop and just below the nearest swing-low support
  (falls back to the nearest support EMA when no pivot is available).
* **Targets** — three scale-out levels in R, lifted toward the analogs' average
  winner / favourable excursion, with T1 snapped beneath overhead swing resistance.
* **Sizing** — from the candidate's risk budget (risk $ / risk-per-share),
  throttled by the regime.
* **Holding period** — from the analogs' average winner hold (regime-adjusted).

It returns plain numbers + narrative summaries; it never places a trade.
"""

from __future__ import annotations

import math

from momentum.tradeplan.config import TradePlanConfig, default_config
from momentum.tradeplan.types import TradePlanInputs, TradePlan, TargetLevel


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


class TradePlanEngine:
    """Turns :class:`TradePlanInputs` into a :class:`TradePlan`."""

    def __init__(self, config: TradePlanConfig | None = None) -> None:
        self.config = config or default_config()

    def plan(self, inputs: TradePlanInputs) -> TradePlan | None:
        """Return a plan, or ``None`` when price/ATR are missing (can't plan)."""
        cfg = self.config
        if inputs.price is None or inputs.atr is None or inputs.price <= 0 or inputs.atr <= 0:
            return None
        entry = inputs.price
        atr = inputs.atr
        atr_pct = atr / entry

        stop, support = self._stop(inputs, entry, atr)
        risk_per_share = entry - stop
        if risk_per_share <= 0:  # degenerate; fall back to a pure ATR stop
            stop = entry - cfg.stop_atr_mult * atr
            support = None
            risk_per_share = entry - stop
        stop_pct = risk_per_share / entry

        targets = self._targets(inputs, entry, risk_per_share)
        blended = sum(t.r_multiple * t.scale_out_pct for t in targets)
        final_rr = targets[-1].r_multiple

        regime_factor = cfg.regime_factor(inputs.regime)
        shares, position_value, risk_dollars, risk_pct = self._size(
            inputs, risk_per_share, regime_factor
        )
        hold_low, hold_high = self._holding(inputs, regime_factor)

        return TradePlan(
            symbol=inputs.symbol,
            entry=entry,
            stop=stop,
            stop_pct=stop_pct,
            risk_per_share=risk_per_share,
            structural_support=support,
            overhead_resistance=inputs.resistance_level,
            targets=targets,
            blended_reward_risk=blended,
            final_reward_risk=final_rr,
            expected_holding_days_low=hold_low,
            expected_holding_days_high=hold_high,
            suggested_shares=shares,
            suggested_position_value=position_value,
            suggested_portfolio_risk_pct=risk_pct,
            suggested_risk_dollars=risk_dollars,
            risk_summary=self._risk_summary(
                inputs, entry, stop, stop_pct, atr, atr_pct, risk_per_share, shares, support
            ),
            reward_summary=self._reward_summary(inputs, targets, blended),
            failure_conditions=self._failure_conditions(inputs, stop, support),
            methodology=self._methodology(inputs, support, regime_factor),
        )

    # -- stop ---------------------------------------------------------------- #
    def _stop(
        self, inputs: TradePlanInputs, entry: float, atr: float
    ) -> tuple[float, float | None]:
        atr_stop = entry - self.config.stop_atr_mult * atr
        # Prefer a confirmed swing-low support (real structure); fall back to the
        # nearest EMA below price when no pivot is available.
        support: float | None = None
        if inputs.support_level is not None and inputs.support_level < entry:
            support = inputs.support_level
        else:
            emas = [
                e for e in (inputs.ema_fast, inputs.ema_mid, inputs.ema_slow) if e and e < entry
            ]
            support = max(emas) if emas else None
        if support is None:
            return atr_stop, None
        structural_stop = support * (1.0 - self.config.support_buffer_pct)
        # The wider (lower) stop respects both ATR noise and structure.
        return min(atr_stop, structural_stop), support

    # -- targets ------------------------------------------------------------- #
    def _targets(
        self, inputs: TradePlanInputs, entry: float, risk_per_share: float
    ) -> tuple[TargetLevel, TargetLevel, TargetLevel]:
        m1, m2, m3 = self.config.target_r_multiples
        # Lift T2 toward the analogs' average winner, T3 toward their MFE.
        if inputs.analog_avg_winner_r is not None:
            m2 = max(m2, round(inputs.analog_avg_winner_r, 2))
        if inputs.analog_avg_mfe_r is not None:
            m3 = max(m3, round(inputs.analog_avg_mfe_r, 2))

        # Snap T1 down to just below the nearest overhead swing resistance when it
        # is the realistic first hurdle (closer than the R-based T1).
        t1_price = entry + m1 * risk_per_share
        res = inputs.resistance_level
        if res is not None and entry < res < t1_price:
            t1_price = res * (1.0 - self.config.support_buffer_pct)
            m1 = (t1_price - entry) / risk_per_share
        m2 = max(m2, m1 + 0.5)  # keep strictly increasing
        m3 = max(m3, m2 + 0.5)

        fracs = self.config.scale_out_fractions
        labels = ("T1", "T2", "T3")
        multiples = (m1, m2, m3)
        levels: list[TargetLevel] = []
        for label, m, frac in zip(labels, multiples, fracs, strict=True):
            price = entry + m * risk_per_share
            levels.append(
                TargetLevel(
                    label=label,
                    price=price,
                    r_multiple=m,
                    gain_pct=(price - entry) / entry,
                    scale_out_pct=frac,
                )
            )
        return levels[0], levels[1], levels[2]

    # -- sizing -------------------------------------------------------------- #
    def _size(
        self, inputs: TradePlanInputs, risk_per_share: float, regime_factor: float
    ) -> tuple[int, float, float, float]:
        equity = inputs.equity if inputs.equity and inputs.equity > 0 else 100_000.0
        if inputs.risk_dollars is not None:
            risk_dollars = inputs.risk_dollars * regime_factor
        elif inputs.risk_pct is not None:
            risk_dollars = inputs.risk_pct * equity * regime_factor
        else:
            risk_dollars = 0.005 * equity * regime_factor  # 0.5% fallback
        shares = max(0, math.floor(risk_dollars / risk_per_share)) if risk_per_share > 0 else 0
        position_value = shares * inputs.price if inputs.price else 0.0
        risk_pct = (shares * risk_per_share) / equity if equity > 0 else 0.0
        return shares, position_value, shares * risk_per_share, risk_pct

    # -- holding period ------------------------------------------------------ #
    def _holding(self, inputs: TradePlanInputs, regime_factor: float) -> tuple[int, int]:
        base = (
            inputs.analog_avg_winner_holding_days
            if inputs.analog_avg_winner_holding_days and inputs.analog_avg_winner_holding_days > 0
            else float(self.config.base_holding_days)
        )
        base *= 0.85 + 0.3 * regime_factor  # bull lets winners run longer
        low = max(self.config.min_holding_days, int(round(base * 0.6)))
        high = max(low + 1, int(round(base * 1.4)))
        return low, high

    # -- narrative ----------------------------------------------------------- #
    def _risk_summary(
        self,
        inputs: TradePlanInputs,
        entry: float,
        stop: float,
        stop_pct: float,
        atr: float,
        atr_pct: float,
        risk_per_share: float,
        shares: int,
        support: float | None,
    ) -> list[str]:
        lines = [
            f"Risk per share ${risk_per_share:.2f} → ${risk_per_share * shares:,.0f} total "
            f"on {shares:,} shares.",
            f"Stop {stop:.2f} ({_fmt_pct(stop_pct)} below {entry:.2f}); "
            f"{self.config.stop_atr_mult:g}×ATR"
            + (f" / just below support {support:.2f}." if support is not None else "."),
            f"Volatility: ATR {atr:.2f} ({_fmt_pct(atr_pct)} of price) per day.",
        ]
        if atr_pct > 0.06:
            lines.append("Elevated volatility — size already reflects the wider ATR stop.")
        return lines

    def _reward_summary(
        self, inputs: TradePlanInputs, targets: tuple[TargetLevel, ...], blended: float
    ) -> list[str]:
        lines = [
            f"{t.label} {t.price:.2f} (+{t.r_multiple:.1f}R, {_fmt_pct(t.gain_pct)}) — "
            f"scale out {int(t.scale_out_pct * 100)}%."
            for t in targets
        ]
        lines.append(f"Blended reward:risk ≈ {blended:.2f}R across the scale-out.")
        if inputs.analog_expectancy_r is not None and inputs.analog_sample_size > 0:
            lines.append(
                f"Analogs: {inputs.analog_expectancy_r:+.2f}R expectancy over "
                f"{inputs.analog_sample_size} similar setups"
                + (
                    f" (win rate {_fmt_pct(inputs.analog_win_rate)})."
                    if inputs.analog_win_rate is not None
                    else "."
                )
            )
        if inputs.resistance_level is not None:
            lines.append(
                f"Overhead swing resistance at {inputs.resistance_level:.2f} — the first hurdle "
                "(T1 snaps just beneath it)."
            )
        elif inputs.distance_from_ath is not None and abs(inputs.distance_from_ath) <= 0.03:
            lines.append("Near all-time highs — little overhead resistance (blue-sky targets).")
        return lines

    def _failure_conditions(
        self, inputs: TradePlanInputs, stop: float, support: float | None
    ) -> list[str]:
        conds = [
            f"Daily close below {stop:.2f} (hard stop) — exit in full.",
            f"Relative volume fades below {self.config.rvol_momentum_floor:g}× — momentum lost.",
            "Market regime flips to Bearish — reduce size or stand aside.",
            f"No progress toward T1 within {self.config.time_stop_days} trading days — time stop.",
        ]
        if support is not None:
            conds.append(f"Loses structural support near {support:.2f} on a closing basis.")
        return conds

    def _methodology(
        self, inputs: TradePlanInputs, support: float | None, regime_factor: float
    ) -> list[str]:
        notes = [
            "Stop from ATR + nearest support EMA; targets in R multiples of that risk.",
            f"Size from the candidate's risk budget × regime factor {regime_factor:g}"
            + (f" ({inputs.regime})." if inputs.regime else "."),
        ]
        if inputs.analog_sample_size > 0:
            notes.append(
                f"Targets and hold lifted toward {inputs.analog_sample_size} historical analogs."
            )
        else:
            notes.append("No historical analogs for this cohort — defaults used for targets/hold.")
        return notes
