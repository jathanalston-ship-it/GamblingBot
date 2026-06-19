"""The dynamic risk-budget engine.

Decides *how much risk* a single trade may take from its conviction and
opportunity tier, then clamps that to the room left under the portfolio-heat
ceiling. It answers "what is this trade's risk budget?" — the per-trade risk
percentage (and dollars) that then drives position sizing in the risk gateway.

Policy:

* **Conviction** sets the base budget — base **0.5%**, high **1%**, extreme **2%**.
* **Home-Run** trades may receive a larger allocation (``home_run_multiplier``),
  but never above the per-trade ceiling (``max_trade_risk_pct``).
* Every budget is finally clamped to the **maximum portfolio risk (5% heat)** —
  a trade gets at most the heat headroom that remains, so the portfolio's
  aggregate open risk can never breach the cap. This is the canonical heat
  semantics from ``risk.heat`` (the same ceiling the risk gateway enforces).

An optional ``throttle`` (≤ 1) composes external drawdown / regime scaling on top,
so this engine slots in front of :class:`~momentum.risk.risk_manager.RiskManager`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from momentum.conviction.engine import ConvictionBand
from momentum.core.constants import EPS
from momentum.opportunity.engine import OpportunityTier
from momentum.risk.heat import remaining_heat_dollars
from momentum.risk.risk_budget_config import RiskBudgetConfig

if TYPE_CHECKING:  # avoid importing pandas-backed risk.types at module load
    from momentum.risk.types import AccountState


@dataclass(frozen=True, slots=True)
class RiskBudgetRequest:
    """Inputs for one risk-budget decision."""

    equity: float
    portfolio_heat_used: float = 0.0  # current open risk / equity (fraction)
    conviction_band: ConvictionBand | None = None
    opportunity_tier: OpportunityTier | None = None
    throttle: float = 1.0  # external drawdown / regime multiplier (<= 1)
    symbol: str | None = None
    signal_id: int | None = None

    @classmethod
    def from_account(
        cls,
        account: AccountState,
        *,
        conviction_band: ConvictionBand | None = None,
        opportunity_tier: OpportunityTier | None = None,
        throttle: float = 1.0,
        symbol: str | None = None,
        signal_id: int | None = None,
    ) -> RiskBudgetRequest:
        """Build a request from the live :class:`AccountState` (uses its heat)."""
        return cls(
            equity=account.equity,
            portfolio_heat_used=account.portfolio_heat,
            conviction_band=conviction_band,
            opportunity_tier=opportunity_tier,
            throttle=throttle,
            symbol=symbol,
            signal_id=signal_id,
        )


@dataclass(frozen=True, slots=True)
class RiskBudget:
    """The auditable risk-budget decision for one trade."""

    symbol: str | None
    equity: float
    conviction_band: ConvictionBand | None
    opportunity_tier: OpportunityTier | None
    home_run: bool
    base_pct: float  # conviction-tier base
    requested_pct: float  # after tier multiplier, per-trade cap and throttle
    granted_pct: float  # after the portfolio-heat clamp
    risk_dollars: float  # granted_pct * equity
    throttle: float
    portfolio_heat_used: float
    portfolio_heat_after: float
    headroom_pct: float
    binding_constraint: str | None  # "portfolio_heat" | "max_trade_risk" | None
    reasons: tuple[str, ...]
    config_hash: str
    signal_id: int | None = None

    @property
    def is_fundable(self) -> bool:
        """Whether any risk budget remains for the trade."""
        return self.granted_pct > 0.0

    @property
    def heat_capped(self) -> bool:
        return self.binding_constraint == "portfolio_heat"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "conviction_band": self.conviction_band.value if self.conviction_band else None,
            "opportunity_tier": self.opportunity_tier.value if self.opportunity_tier else None,
            "home_run": self.home_run,
            "base_pct": round(self.base_pct, 6),
            "requested_pct": round(self.requested_pct, 6),
            "granted_pct": round(self.granted_pct, 6),
            "risk_dollars": round(self.risk_dollars, 4),
            "throttle": round(self.throttle, 6),
            "portfolio_heat_used": round(self.portfolio_heat_used, 6),
            "portfolio_heat_after": round(self.portfolio_heat_after, 6),
            "headroom_pct": round(self.headroom_pct, 6),
            "binding_constraint": self.binding_constraint,
            "is_fundable": self.is_fundable,
            "reasons": list(self.reasons),
            "config_hash": self.config_hash,
        }

    def __str__(self) -> str:
        tail = f" [{self.binding_constraint}]" if self.binding_constraint else ""
        return (
            f"<RiskBudget {self.symbol or '-'} {self.granted_pct:.2%} "
            f"(${self.risk_dollars:,.0f}){tail}>"
        )


class DynamicRiskBudgetEngine:
    """Turns conviction + opportunity tier + portfolio heat into a per-trade budget."""

    def __init__(self, config: RiskBudgetConfig | None = None) -> None:
        self.config = config or RiskBudgetConfig()

    # -- public API --------------------------------------------------------- #
    def budget(self, request: RiskBudgetRequest) -> RiskBudget:
        cfg = self.config
        band = request.conviction_band
        tier = request.opportunity_tier
        is_home_run = tier is OpportunityTier.HOME_RUN

        base_pct = self._base_pct(band)
        multiplier = self._tier_multiplier(tier)
        leveraged_pct = base_pct * multiplier
        capped_pct = min(leveraged_pct, cfg.max_trade_risk_pct)
        throttle = max(0.0, request.throttle)
        requested_pct = capped_pct * throttle

        # Clamp to the room left under the portfolio-heat ceiling (the 5% cap).
        equity = max(0.0, request.equity)
        heat_used = max(0.0, request.portfolio_heat_used)
        headroom_dollars = remaining_heat_dollars(
            total_open_risk=heat_used * equity,
            equity=equity,
            max_heat=cfg.max_portfolio_heat,
        )
        headroom_pct = headroom_dollars / equity if equity > 0 else 0.0
        granted_pct = min(requested_pct, headroom_pct)
        risk_dollars = granted_pct * equity

        binding = self._binding(leveraged_pct, capped_pct, requested_pct, granted_pct)
        reasons = self._reasons(
            band,
            tier,
            is_home_run,
            base_pct,
            multiplier,
            leveraged_pct,
            capped_pct,
            throttle,
            requested_pct,
            heat_used,
            headroom_pct,
            granted_pct,
            risk_dollars,
            binding,
        )

        return RiskBudget(
            symbol=request.symbol.upper() if request.symbol else None,
            equity=request.equity,
            conviction_band=band,
            opportunity_tier=tier,
            home_run=is_home_run,
            base_pct=base_pct,
            requested_pct=round(requested_pct, 6),
            granted_pct=round(granted_pct, 6),
            risk_dollars=round(risk_dollars, 4),
            throttle=throttle,
            portfolio_heat_used=heat_used,
            portfolio_heat_after=round(heat_used + granted_pct, 6),
            headroom_pct=round(headroom_pct, 6),
            binding_constraint=binding,
            reasons=reasons,
            config_hash=cfg.config_hash(),
            signal_id=request.signal_id,
        )

    def per_trade_pct(
        self,
        conviction_band: ConvictionBand | None,
        opportunity_tier: OpportunityTier | None = None,
        *,
        throttle: float = 1.0,
    ) -> float:
        """The per-trade risk pct (after tier multiplier, cap and throttle), pre-heat."""
        capped = min(
            self._base_pct(conviction_band) * self._tier_multiplier(opportunity_tier),
            self.config.max_trade_risk_pct,
        )
        return capped * max(0.0, throttle)

    # -- helpers ------------------------------------------------------------ #
    def _base_pct(self, band: ConvictionBand | None) -> float:
        cfg = self.config
        if band is ConvictionBand.EXTREME:
            return cfg.extreme_conviction_risk_pct
        if band is ConvictionBand.HIGH:
            return cfg.high_conviction_risk_pct
        return cfg.base_risk_pct  # LOW, MEDIUM or unknown -> base

    def _tier_multiplier(self, tier: OpportunityTier | None) -> float:
        cfg = self.config
        if tier is OpportunityTier.HOME_RUN:
            return cfg.home_run_multiplier
        if tier is OpportunityTier.ENHANCED:
            return cfg.enhanced_multiplier
        return 1.0

    @staticmethod
    def _binding(
        leveraged_pct: float, capped_pct: float, requested_pct: float, granted_pct: float
    ) -> str | None:
        if granted_pct < requested_pct - EPS:
            return "portfolio_heat"
        if capped_pct < leveraged_pct - EPS:
            return "max_trade_risk"
        return None

    def _reasons(
        self,
        band: ConvictionBand | None,
        tier: OpportunityTier | None,
        is_home_run: bool,
        base_pct: float,
        multiplier: float,
        leveraged_pct: float,
        capped_pct: float,
        throttle: float,
        requested_pct: float,
        heat_used: float,
        headroom_pct: float,
        granted_pct: float,
        risk_dollars: float,
        binding: str | None,
    ) -> tuple[str, ...]:
        cfg = self.config
        label = band.value.title() if band else "default"
        out = [f"Conviction {label} → base {base_pct:.2%}."]
        if is_home_run:
            line = f"Home Run → ×{multiplier:.2f} = {leveraged_pct:.2%}"
            if capped_pct < leveraged_pct - EPS:
                line += f", capped at per-trade max {cfg.max_trade_risk_pct:.2%}"
            out.append(line + ".")
        elif tier is OpportunityTier.ENHANCED and multiplier > 1.0:
            out.append(f"Enhanced → ×{multiplier:.2f} = {capped_pct:.2%}.")
        if throttle < 1.0 - EPS:
            out.append(f"Throttle ×{throttle:.2f} → {requested_pct:.2%}.")
        out.append(
            f"Portfolio heat {heat_used:.2%} used; {headroom_pct:.2%} headroom under the "
            f"{cfg.max_portfolio_heat:.2%} cap."
        )
        if binding == "portfolio_heat":
            out.append(f"Heat-capped → granted {granted_pct:.2%} (${risk_dollars:,.0f}).")
        else:
            out.append(f"Granted {granted_pct:.2%} (${risk_dollars:,.0f}).")
        return tuple(out)
