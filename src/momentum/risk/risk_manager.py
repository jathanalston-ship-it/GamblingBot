"""The RISK GATEWAY — the single chokepoint for all risk policy.

``RiskManager.evaluate(proposal, account)`` is the one place a trade is sized,
stopped and vetted. It composes volatility, sizing, stops, exposure,
correlation, heat, drawdown and circuit-breaker logic in one auditable pass and
returns a :class:`RiskAssessment` (``APPROVE`` | ``RESIZE`` | ``VETO``) with the
sized quantity, stop level, effective risk and a human-readable reason for every
decision — including rejections. No order may be created without one.

Order of checks (per docs/RISK_MANAGEMENT.md): the stop defines ``R``; the
per-trade risk budget is throttled by drawdown and market regime *before*
sizing; then cheap local caps (per-name weight), then portfolio-wide checks
(sector, correlation, heat, slots), and finally the hard circuit breakers.
"""

from __future__ import annotations

from momentum.core.enums import RegimeState, RiskVerdict, Side
from momentum.risk import drawdown as dd
from momentum.risk import exposure, heat, limits
from momentum.risk.correlation import correlated_cluster_size, max_correlation_with_open
from momentum.risk.position_sizing import shares_for_weight, size_position
from momentum.risk.risk_config import RiskConfig
from momentum.risk.stops import initial_stop, stop_distance
from momentum.risk.types import AccountState, RiskAssessment, TradeProposal


class RiskManager:
    """Sizes, stops and vets every proposed trade against the full risk policy."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    # -- public API --------------------------------------------------------- #
    def evaluate(
        self,
        proposal: TradeProposal,
        account: AccountState,
        *,
        run_id: str | None = None,
    ) -> RiskAssessment:
        cfg = self.config
        side = proposal.side
        entry = proposal.entry_ref
        atr = proposal.atr
        equity = account.equity

        existing_gross = sum(p.market_value for p in account.open_positions)
        existing_signed = sum(p.signed_market_value for p in account.open_positions)
        heat_before = account.portfolio_heat
        base_pct = cfg.sizing.risk_per_trade_pct

        # --- stop defines R ------------------------------------------------- #
        stop = initial_stop(entry, atr, cfg.stops.initial_atr_multiple, side)
        dist = stop_distance(entry, stop)

        dd_mult = dd.risk_multiplier(account.drawdown, cfg.drawdown_throttle)
        regime_mult = self._regime_multiplier(account.regime)
        eff_pct = base_pct * dd_mult * regime_mult
        risk_dollars = equity * eff_pct

        ctx = _Context(
            proposal=proposal,
            account=account,
            run_id=run_id,
            entry=entry,
            atr=atr,
            stop=stop,
            dist=dist,
            base_pct=base_pct,
            eff_pct=eff_pct,
            risk_dollars=risk_dollars,
            dd_mult=dd_mult,
            regime_mult=regime_mult,
            heat_before=heat_before,
            existing_gross=existing_gross,
            existing_signed=existing_signed,
            method=cfg.sizing.method.value,
        )

        # --- guards that need no sizing ------------------------------------ #
        if equity <= 0:
            return ctx.veto(0, "insufficient_equity", "account equity is non-positive")
        if dist <= 0 or atr <= 0:
            return ctx.veto(0, "invalid_stop", "stop distance / ATR is non-positive")
        if regime_mult <= 0:
            return ctx.veto(0, "regime", f"regime {account.regime} disallows new entries")

        # --- size from the throttled budget -------------------------------- #
        requested = size_position(
            cfg.sizing,
            equity=equity,
            risk_per_trade_pct=eff_pct,
            stop_distance=dist,
            price=entry,
            sigma_annual=proposal.volatility_annual,
        )
        ctx.requested = requested
        if requested <= 0:
            return ctx.veto(0, "insufficient_risk_budget", "sized to zero shares")

        shares = requested
        reasons: list[str] = []
        binding: str | None = None

        # --- per-name weight cap (resize) ---------------------------------- #
        cap = shares_for_weight(equity, entry, cfg.sizing.max_position_weight)
        if shares > cap:
            shares = cap
            binding = "max_position_weight"
            reasons.append(
                f"resized to {cap} for max position weight {cfg.sizing.max_position_weight:.0%}"
            )

        # --- sector concentration (resize / veto) -------------------------- #
        if proposal.sector is not None:
            room = exposure.shares_to_fit_sector(
                existing_sector_notional=account.sector_notional(proposal.sector),
                equity=equity,
                price=entry,
                max_sector_weight=cfg.portfolio_limits.max_sector_weight,
            )
            if shares > room:
                if room <= 0:
                    return ctx.veto(
                        0,
                        "sector_concentration",
                        f"sector {proposal.sector} at the "
                        f"{cfg.portfolio_limits.max_sector_weight:.0%} cap",
                    )
                shares = room
                binding = "sector_concentration"
                reasons.append(f"resized to {room} for sector cap")

        # --- correlation / clustering (veto) ------------------------------- #
        if cfg.correlation.enabled and proposal.returns is not None:
            open_returns = {
                p.symbol: p.returns for p in account.open_positions if p.returns is not None
            }
            max_corr, peer = max_correlation_with_open(
                proposal.returns, open_returns, lookback=cfg.correlation.lookback_days
            )
            if max_corr is not None and max_corr > cfg.correlation.max_pairwise_correlation:
                return ctx.veto(
                    0,
                    "correlation",
                    f"correlation {max_corr:.2f} with {peer} exceeds "
                    f"{cfg.correlation.max_pairwise_correlation:.2f}",
                )
            cluster = correlated_cluster_size(
                proposal.returns,
                open_returns,
                threshold=cfg.correlation.max_pairwise_correlation,
                lookback=cfg.correlation.lookback_days,
            )
            if cluster >= cfg.correlation.max_cluster_positions:
                return ctx.veto(
                    0,
                    "correlation_cluster",
                    f"{cluster} correlated positions already open",
                )

        # --- portfolio heat (resize / veto) -------------------------------- #
        remaining = heat.remaining_heat_dollars(
            total_open_risk=account.total_open_risk,
            equity=equity,
            max_heat=cfg.portfolio_limits.max_portfolio_heat,
        )
        if shares * dist > remaining:
            fit = heat.shares_to_fit_heat(remaining, dist)
            if fit <= 0:
                return ctx.veto(
                    0,
                    "portfolio_heat",
                    f"no heat budget left under {cfg.portfolio_limits.max_portfolio_heat:.0%}",
                )
            shares = min(shares, fit)
            binding = "portfolio_heat"
            reasons.append(f"resized to {fit} to fit portfolio heat")

        # --- slot limit (veto) --------------------------------------------- #
        if limits.slot_limit_reached(account.num_positions, cfg.portfolio_limits):
            return ctx.veto(
                0,
                "max_open_positions",
                f"already at {cfg.portfolio_limits.max_open_positions} open positions",
            )

        # --- circuit breakers, evaluated last (hard halt) ------------------ #
        if limits.daily_loss_breached(account.daily_pnl_pct, cfg.circuit_breakers):
            return ctx.veto(
                0,
                "daily_loss_kill_switch",
                f"daily loss {account.daily_pnl_pct:.2%} hit the kill switch",
            )
        if limits.consecutive_losses_breached(account.consecutive_losses, cfg.circuit_breakers):
            return ctx.veto(
                0,
                "consecutive_losses",
                f"{account.consecutive_losses} consecutive losses — paused for review",
            )

        if shares <= 0:
            return ctx.veto(0, binding or "zero_size", "sized to zero after constraints")

        verdict = RiskVerdict.RESIZE if shares < requested else RiskVerdict.APPROVE
        if verdict is RiskVerdict.APPROVE:
            reasons.append("approved at full risk")
        return ctx.build(verdict, shares, binding, reasons)

    # -- helpers ------------------------------------------------------------ #
    def _regime_multiplier(self, regime: RegimeState | None) -> float:
        rc = self.config.regime
        if not rc.enabled or regime is None:
            return 1.0
        return {
            RegimeState.BULLISH: rc.bullish_multiplier,
            RegimeState.NEUTRAL: rc.neutral_multiplier,
            RegimeState.BEARISH: rc.bearish_multiplier,
        }[regime]


class _Context:
    """Carries decision context so assessments are built consistently."""

    def __init__(
        self,
        *,
        proposal: TradeProposal,
        account: AccountState,
        run_id: str | None,
        entry: float,
        atr: float,
        stop: float,
        dist: float,
        base_pct: float,
        eff_pct: float,
        risk_dollars: float,
        dd_mult: float,
        regime_mult: float,
        heat_before: float,
        existing_gross: float,
        existing_signed: float,
        method: str,
    ) -> None:
        self.p = proposal
        self.a = account
        self.run_id = run_id
        self.entry = entry
        self.atr = atr
        self.stop = stop
        self.dist = dist
        self.base_pct = base_pct
        self.eff_pct = eff_pct
        self.risk_dollars = risk_dollars
        self.dd_mult = dd_mult
        self.regime_mult = regime_mult
        self.heat_before = heat_before
        self.existing_gross = existing_gross
        self.existing_signed = existing_signed
        self.method = method
        self.requested = 0

    def build(
        self,
        verdict: RiskVerdict,
        shares: int,
        binding: str | None,
        reasons: list[str],
    ) -> RiskAssessment:
        equity = self.a.equity
        side: Side = self.p.side
        notional = shares * self.entry
        weight = notional / equity if equity > 0 else 0.0
        added_risk = shares * self.dist
        heat_after = (self.a.total_open_risk + added_risk) / equity if equity > 0 else 0.0
        gross_after = (self.existing_gross + notional) / equity if equity > 0 else 0.0
        net_after = (self.existing_signed + side.sign * notional) / equity if equity > 0 else 0.0
        return RiskAssessment(
            verdict=verdict,
            symbol=self.p.symbol.upper(),
            method=self.method,
            equity=equity,
            requested_shares=self.requested,
            approved_shares=shares,
            entry_ref=self.entry,
            initial_stop=self.stop,
            stop_distance=self.dist,
            risk_dollars=self.risk_dollars,
            risk_per_trade_pct=self.eff_pct,
            base_risk_per_trade_pct=self.base_pct,
            atr=self.atr,
            vol_estimate=self.p.volatility_annual,
            target_notional=notional,
            target_weight=weight,
            portfolio_heat_before=self.heat_before,
            portfolio_heat_after=heat_after,
            gross_exposure_after=gross_after,
            net_exposure_after=net_after,
            drawdown_multiplier=self.dd_mult,
            regime_multiplier=self.regime_mult,
            binding_constraint=binding,
            reasons=tuple(reasons),
            regime=self.a.regime,
            signal_id=self.p.signal_id,
            run_id=self.run_id,
        )

    def veto(self, shares: int, binding: str, reason: str) -> RiskAssessment:
        return self.build(RiskVerdict.VETO, shares, binding, [reason])
