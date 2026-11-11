"""Trade-plan generation (pure logic).

Turns a scan candidate into the concrete plan the strategy trades
(:mod:`momentum.strategy`):

* **Stop** — ``entry − stop_atr_mult × ATR`` (3×ATR by default; optionally
  widened below swing-low support with ``use_structural_stop``).
* **Size** — a fixed fraction of the account at risk per trade, capped by the
  per-position limit (:func:`momentum.strategy.rules.position_size`).
* **Exit** — there is no profit target. The position is held until a daily
  close below the trend-exit level (the prior N-day low) or the stop. The
  three "targets" are R milestones for tracking progress only.
* **Holding period** — from the analogs' average winner hold when history exists.

It returns plain numbers + narrative summaries; it never places a trade.
"""

from __future__ import annotations

from momentum.strategy.config import StrategyConfig
from momentum.strategy.config import default_config as default_strategy
from momentum.strategy.rules import initial_stop, position_size
from momentum.tradeplan.config import TradePlanConfig, default_config
from momentum.tradeplan.types import TradePlanInputs, TradePlan, TargetLevel


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


class TradePlanEngine:
    """Turns :class:`TradePlanInputs` into a :class:`TradePlan`."""

    def __init__(
        self, config: TradePlanConfig | None = None, strategy: StrategyConfig | None = None
    ) -> None:
        self.config = config or default_config()
        self.strategy = strategy or default_strategy()

    @property
    def stop_atr_mult(self) -> float:
        """The stop multiple in force (the strategy's unless explicitly overridden)."""
        override = self.config.stop_atr_mult
        return override if override is not None else self.strategy.stop_atr_mult

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
            stop = entry - self.stop_atr_mult * atr
            support = None
            risk_per_share = entry - stop
        stop_pct = risk_per_share / entry

        targets = self._targets(inputs, entry, risk_per_share)
        blended = sum(t.r_multiple * t.scale_out_pct for t in targets)
        final_rr = targets[-1].r_multiple

        regime_factor = cfg.regime_factor(inputs.regime)
        shares, position_value, risk_dollars, risk_pct = self._size(
            inputs, entry, stop, regime_factor
        )
        hold_low, hold_high = self._holding(inputs, regime_factor)
        exit_level = (
            inputs.exit_level if inputs.exit_level is not None and inputs.exit_level > 0 else None
        )

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
            exit_level=exit_level,
            exit_rule=self._exit_rule(exit_level),
            risk_summary=self._risk_summary(
                inputs, entry, stop, stop_pct, atr, atr_pct, risk_per_share, shares, support
            ),
            reward_summary=self._reward_summary(inputs, targets, exit_level),
            failure_conditions=self._failure_conditions(inputs, stop, exit_level),
            methodology=self._methodology(inputs, support),
        )

    # -- stop ---------------------------------------------------------------- #
    def _stop(
        self, inputs: TradePlanInputs, entry: float, atr: float
    ) -> tuple[float, float | None]:
        if self.config.stop_atr_mult is None:
            atr_stop = initial_stop(entry, atr, self.strategy)
        else:
            atr_stop = entry - self.config.stop_atr_mult * atr
        if not self.config.use_structural_stop:
            return atr_stop, None
        # Optional: respect real structure too. Prefer a confirmed swing-low
        # support; fall back to the nearest EMA below price.
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

    # -- milestones ---------------------------------------------------------- #
    def _targets(
        self, inputs: TradePlanInputs, entry: float, risk_per_share: float
    ) -> tuple[TargetLevel, TargetLevel, TargetLevel]:
        """Three R milestones (progress markers — nothing is sold at them)."""
        fracs = self.config.scale_out_fractions
        labels = ("T1", "T2", "T3")
        levels: list[TargetLevel] = []
        for label, m, frac in zip(labels, self.config.target_r_multiples, fracs, strict=True):
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
        self, inputs: TradePlanInputs, entry: float, stop: float, regime_factor: float
    ) -> tuple[int, float, float, float]:
        """Shares / position value / risk dollars / risk % — the strategy's sizing.

        An explicit ``risk_dollars`` / ``risk_pct`` on the inputs overrides the
        strategy's per-trade risk; the per-position cap always applies.
        """
        equity = inputs.equity if inputs.equity and inputs.equity > 0 else 100_000.0
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            return 0, 0.0, 0.0, 0.0
        strategy = self.strategy
        if inputs.risk_dollars is not None and equity > 0:
            risk_fraction = inputs.risk_dollars / equity
        elif inputs.risk_pct is not None:
            risk_fraction = inputs.risk_pct
        else:
            risk_fraction = strategy.risk_per_trade_pct
        risk_fraction *= regime_factor
        if risk_fraction <= 0:
            return 0, 0.0, 0.0, 0.0
        sized = strategy.model_copy(update={"risk_per_trade_pct": min(risk_fraction, 0.05)})
        shares = position_size(equity, entry, stop, sized)
        position_value = shares * entry
        risk_dollars = shares * risk_per_share
        return shares, position_value, risk_dollars, (risk_dollars / equity if equity > 0 else 0.0)

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
    def _exit_rule(self, exit_level: float | None) -> str:
        days = self.strategy.exit_lookback
        if exit_level is None:
            return f"Hold until a daily close below the {days}-day low, or the stop."
        return (
            f"Hold until a daily close below {exit_level:.2f} (the {days}-day low, which "
            "rises as the stock climbs), or the stop — whichever comes first."
        )

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
            f"If the stop is hit you lose about ${risk_per_share * shares:,.0f} "
            f"(${risk_per_share:.2f} a share on {shares:,} shares).",
            f"Stop {stop:.2f} — {_fmt_pct(stop_pct)} below the {entry:.2f} entry "
            f"({self.stop_atr_mult:g}× the stock's average daily range)"
            + (f", just below support at {support:.2f}." if support is not None else "."),
            f"Typical daily move: {atr:.2f} ({_fmt_pct(atr_pct)} of price).",
        ]
        if atr_pct > 0.06:
            lines.append("This is a volatile stock — the position is sized smaller to match.")
        return lines

    def _reward_summary(
        self,
        inputs: TradePlanInputs,
        targets: tuple[TargetLevel, ...],
        exit_level: float | None,
    ) -> list[str]:
        lines = [
            "No profit target: winners are held until the trend breaks. Most of this "
            "strategy's profit comes from a minority of large winners, so they are not "
            "sold early.",
            self._exit_rule(exit_level),
            "Milestones (not sell orders): "
            + ", ".join(f"{t.price:.2f} = +{t.r_multiple:g}R" for t in targets)
            + ".",
        ]
        if inputs.analog_expectancy_r is not None and inputs.analog_sample_size > 0:
            lines.append(
                f"Your own history in similar setups: {inputs.analog_expectancy_r:+.2f}R "
                f"average over {inputs.analog_sample_size} closed trades."
            )
        return lines

    def _failure_conditions(
        self, inputs: TradePlanInputs, stop: float, exit_level: float | None
    ) -> list[str]:
        days = self.strategy.exit_lookback
        conds = [f"Price trades at or below the stop {stop:.2f} — sell everything."]
        if exit_level is not None:
            conds.append(
                f"A daily close below {exit_level:.2f} (the {days}-day low) — the trend "
                "is broken; sell at the next open."
            )
        else:
            conds.append(f"A daily close below the {days}-day low — sell at the next open.")
        if inputs.market_uptrend is False:
            conds.append(
                "The market is in a downtrend right now — the strategy opens no new "
                "positions until it recovers."
            )
        return conds

    def _methodology(self, inputs: TradePlanInputs, support: float | None) -> list[str]:
        strategy = self.strategy
        notes = [
            f"Stop = entry − {self.stop_atr_mult:g} × ATR({strategy.atr_period}).",
            f"Size = {strategy.risk_per_trade_pct * 100:g}% of the account at risk, "
            f"never more than {strategy.max_position_pct * 100:g}% of the account in one stock.",
            f"Exit = stop, or a daily close below the {strategy.exit_lookback}-day low.",
        ]
        if support is not None:
            notes.append(f"Stop widened to sit below swing support at {support:.2f}.")
        return notes
