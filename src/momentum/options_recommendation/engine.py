"""The options-recommendation engine (pure logic).

Given an options-*eligible* setup, choose the best way to express it with a
defined-risk, conservative options structure and emit a concrete (approximate)
contract: expiration, strike, delta, risk level, max loss, target profit and a
suggested allocation. Structures follow the fixed platform preference order —
1. Deep ITM Calls, 2. ATM Calls, 3. Vertical Call Spreads: Deep ITM is the
conservative default and the engine only steps away on a clear IV signal (rich IV
⇒ spread, cheap IV with a large move ⇒ ATM). Per-structure suitability scores are
retained purely as a diagnostic for the choice.

The engine deliberately AVOIDS low liquidity, wide spreads, lottery contracts and
short-dated options: the first two are hard gates that veto the recommendation,
the latter two are guaranteed by construction (a minimum long delta and a minimum
days-to-expiry floor) and surfaced as passing gates. Every result ships explicit
risk disclosures and **never** routes an order.
"""

from __future__ import annotations

import math

from momentum.instruments.scoring import band, down, up
from momentum.options_recommendation.config import (
    OptionsRecommendationConfig,
    StructureWeights,
    default_config,
)
from momentum.options_recommendation.pricing import (
    annual_vol,
    atm_premium,
    call_premium,
    call_value_at,
    per_contract,
)
from momentum.options_recommendation.types import (
    AvoidGate,
    ContractRecommendation,
    OptionsRecommendation,
    OptionStructure,
    RecommendationInputs,
    RiskLevel,
    StructureCandidate,
)

# Hard gates that veto the recommendation when they fail.
_HARD_GATES = frozenset({"options_eligibility", "liquidity", "option_spread", "lottery"})


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _strike_increment(price: float) -> float:
    """A plausible listed-strike increment for the underlying's price tier."""
    if price >= 200:
        return 5.0
    if price >= 100:
        return 2.5
    if price >= 25:
        return 1.0
    return 0.5


def _round_strike(value: float, price: float) -> float:
    inc = _strike_increment(price)
    return max(inc, round(value / inc) * inc)


def _blend(weights: StructureWeights, comps: dict[str, float]) -> float:
    """Weighted mean over the factors that carry weight (re-normalized)."""
    w = weights.as_dict()
    num = sum(w[name] * value for name, value in comps.items())
    den = sum(w[name] for name in comps)
    return num / den if den > 0 else 0.0


class OptionsRecommendationEngine:
    """Recommends a defined-risk options structure for an eligible setup."""

    def __init__(self, config: OptionsRecommendationConfig | None = None) -> None:
        self.config = config or default_config()

    def recommend(self, inputs: RecommendationInputs) -> OptionsRecommendation:
        cfg = self.config
        sym = inputs.symbol.upper()
        horizon = inputs.horizon_days or cfg.sizing.default_horizon_days
        risk_budget = inputs.risk_budget or cfg.sizing.default_risk_budget
        equity = inputs.account_equity or cfg.sizing.default_equity
        iv_rank = inputs.iv_rank if inputs.iv_rank is not None else 0.5

        expected_move = inputs.expected_move_pct
        if expected_move is None and inputs.atr_pct is not None and inputs.atr_pct > 0:
            expected_move = inputs.atr_pct * math.sqrt(horizon)
        move_for_calc = expected_move if expected_move is not None else cfg.bands.move_small

        candidates = self._score(expected_move, iv_rank, horizon, risk_budget, inputs.dollar_volume)
        winner = self._select(candidates, iv_rank, move_for_calc)

        contract = self._build_contract(
            winner.structure, inputs, horizon, move_for_calc, iv_rank, risk_budget, equity
        )
        gates = self._gates(inputs, contract)
        blocking = [g for g in gates if not g.passed and g.name in _HARD_GATES]
        recommended = inputs.setup_eligible and not blocking

        disclosures = self._disclosures(winner.structure, contract, iv_rank, risk_budget, gates)
        summary = self._summary(sym, recommended, winner.structure, contract, gates)

        return OptionsRecommendation(
            symbol=sym,
            recommended=recommended,
            structure=winner.structure,
            contract=contract,
            expected_move_pct=expected_move,
            candidates=tuple(candidates),
            gates=tuple(gates),
            risk_disclosures=disclosures,
            summary=summary,
            config_hash=cfg.config_hash(),
        )

    # -- structure scoring -------------------------------------------------- #
    def _score(
        self,
        move: float | None,
        iv_rank: float,
        horizon: int,
        risk_budget: float,
        dollar_volume: float | None,
    ) -> list[StructureCandidate]:
        b = self.config.bands
        em = move if move is not None else b.move_small
        big_move = up(em, b.move_small, b.move_large)
        mod_move = band(em, b.move_small * 0.5, b.move_small, b.move_large * 0.7, b.move_large)
        iv_cheap = down(iv_rank, b.iv_low, b.iv_high)
        iv_rich = up(iv_rank, b.iv_low, b.iv_high)
        short_h = band(
            float(horizon),
            5.0,
            float(b.short_horizon_days),
            float(b.medium_horizon_days),
            float(b.long_horizon_days),
        )
        long_h = up(float(horizon), float(b.medium_horizon_days), float(b.long_horizon_days))
        tight_budget = down(risk_budget, b.budget_small, b.budget_large)
        liquidity = (
            up(dollar_volume, b.liquidity_floor, b.liquidity_good)
            if dollar_volume is not None
            else 0.5
        )

        comps: dict[OptionStructure, dict[str, float]] = {
            OptionStructure.DEEP_ITM_CALL: {
                "base": 1.0,
                "move": big_move,
                "iv": iv_rich,  # deep ITM minimizes extrinsic paid when IV is rich
                "horizon": long_h,  # low theta => can hold
                "budget": tight_budget,
                "liquidity": liquidity,
            },
            OptionStructure.ATM_CALL: {
                "move": big_move,  # convexity shines on a large move
                "iv": iv_cheap,  # cheap premium => buy at the money
                "horizon": short_h,
                "budget": tight_budget,
                "liquidity": liquidity,
            },
            OptionStructure.VERTICAL_SPREAD: {
                "iv": iv_rich,  # rich premium => sell upside to finance the long
                "move": mod_move,  # moderate (capped) move acceptable
                "horizon": short_h,
                "budget": tight_budget,
                "liquidity": liquidity,
            },
        }
        out: list[StructureCandidate] = []
        for structure in OptionStructure:
            c = comps[structure]
            score = _blend(self.config.weights.for_key(structure.value), c)
            out.append(StructureCandidate(structure, score, c))
        return out

    def _select(
        self, candidates: list[StructureCandidate], iv_rank: float, move: float
    ) -> StructureCandidate:
        """Honour the preference order Deep ITM → ATM → Vertical Spread.

        Deep ITM is the conservative default; we only step away on a clear IV
        signal. Rich IV ⇒ a spread (sell premium); cheap IV with a large expected
        move ⇒ ATM (convexity per dollar). The ``score`` on each candidate is
        retained purely as a transparency/diagnostic for the choice.
        """
        b = self.config.bands
        by_struct = {c.structure: c for c in candidates}
        if iv_rank >= b.iv_high:
            return by_struct[OptionStructure.VERTICAL_SPREAD]
        big_move = up(move, b.move_small, b.move_large)
        if iv_rank <= b.iv_low and big_move >= self.config.atm_convexity_move_score:
            return by_struct[OptionStructure.ATM_CALL]
        return by_struct[OptionStructure.DEEP_ITM_CALL]

    # -- contract construction ---------------------------------------------- #
    def _build_contract(
        self,
        structure: OptionStructure,
        inputs: RecommendationInputs,
        horizon: int,
        move: float,
        iv_rank: float,
        risk_budget: float,
        equity: float,
    ) -> ContractRecommendation:
        cfg = self.config
        price = inputs.price
        exp = cfg.expiration
        dte = int(_clamp(round(horizon * exp.horizon_multiple), exp.min_dte, exp.max_dte))
        vol = annual_vol(inputs.iv, inputs.atr_pct, cfg.pricing.fallback_annual_vol)
        atm_ext = atm_premium(price, vol, dte, cfg.pricing.atm_premium_coeff)
        target_price = price * (1.0 + move)

        short_strike: float | None = None
        short_delta: float | None = None
        if structure is OptionStructure.DEEP_ITM_CALL:
            delta = cfg.deltas.deep_itm_delta
            strike = _round_strike(price * (1.0 - cfg.moneyness.deep_itm_moneyness), price)
        elif structure is OptionStructure.ATM_CALL:
            delta = cfg.deltas.atm_delta
            strike = _round_strike(price, price)
        else:  # VERTICAL_SPREAD
            delta = cfg.deltas.spread_long_delta
            short_delta = cfg.deltas.spread_short_delta
            strike = _round_strike(price * (1.0 - cfg.moneyness.spread_long_moneyness), price)
            lo = strike + price * cfg.spread_width.min_width_pct
            hi = strike + price * cfg.spread_width.max_width_pct
            short_strike = _round_strike(_clamp(target_price, lo, hi), price)
            if short_strike <= strike:  # guarantee a positive width
                short_strike = strike + _strike_increment(price)

        long_prem = call_premium(price, strike, delta, atm_ext)
        if structure is OptionStructure.VERTICAL_SPREAD and short_strike is not None:
            assert short_delta is not None
            width = short_strike - strike
            short_prem = call_premium(price, short_strike, short_delta, atm_ext)
            net_debit = _clamp(long_prem - short_prem, 0.01 * width, width)
            cost_ps = net_debit
            value_ps = _clamp(
                call_value_at(target_price, strike) - call_value_at(target_price, short_strike),
                0.0,
                width,
            )
        else:
            cost_ps = long_prem
            value_ps = call_value_at(target_price, strike)

        cost_pc = per_contract(cost_ps)
        max_loss_pc = cost_pc  # debit structures: max loss == premium paid
        profit_pc = per_contract(value_ps - cost_ps)
        rr = profit_pc / max_loss_pc if max_loss_pc > 0 else None

        contracts = self._size(max_loss_pc, cost_pc, risk_budget, equity)
        allocation = contracts * cost_pc
        risk_level = self._risk_level(structure, delta, dte, allocation / equity if equity else 0.0)

        return ContractRecommendation(
            structure=structure,
            expiration_days=dte,
            strike=strike,
            delta=delta,
            short_strike=short_strike,
            short_delta=short_delta,
            risk_level=risk_level,
            contracts=contracts,
            est_premium_per_contract=cost_pc,
            max_loss=contracts * max_loss_pc,
            target_profit=contracts * profit_pc,
            suggested_allocation=allocation,
            allocation_pct=allocation / equity if equity else 0.0,
            reward_to_risk=rr,
        )

    def _size(self, max_loss_pc: float, cost_pc: float, risk_budget: float, equity: float) -> int:
        if max_loss_pc <= 0 or cost_pc <= 0:
            return 0
        by_risk = int(risk_budget // max_loss_pc)
        max_capital = equity * self.config.sizing.max_capital_pct
        by_capital = int(max_capital // cost_pc)
        return max(0, min(by_risk, by_capital))

    def _risk_level(
        self, structure: OptionStructure, delta: float, dte: int, allocation_pct: float
    ) -> RiskLevel:
        exp = self.config.expiration
        moneyness_risk = 1.0 - delta  # lower delta (more OTM) => riskier
        theta_risk = down(float(dte), float(exp.min_dte), 90.0)
        alloc_risk = up(allocation_pct, 0.03, self.config.sizing.max_capital_pct)
        score = 0.45 * moneyness_risk + 0.30 * theta_risk + 0.25 * alloc_risk
        if structure.is_spread:  # defined and capped => lower
            score *= 0.8
        if score < 0.33:
            return RiskLevel.LOW
        if score < 0.60:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH

    # -- AVOID gates -------------------------------------------------------- #
    def _gates(
        self, inputs: RecommendationInputs, contract: ContractRecommendation
    ) -> list[AvoidGate]:
        cfg = self.config
        gates: list[AvoidGate] = []

        if not inputs.setup_eligible:
            gates.append(
                AvoidGate(
                    "options_eligibility",
                    False,
                    "setup is shares-preferred (failed the options-eligibility gate)",
                )
            )
        else:
            gates.append(AvoidGate("options_eligibility", True, "setup is options-eligible"))

        adv = inputs.dollar_volume
        floor = cfg.gates.min_underlying_dollar_volume
        if adv is None:
            gates.append(AvoidGate("liquidity", True, "underlying volume unknown (not gated)"))
        else:
            ok = adv >= floor
            gates.append(
                AvoidGate(
                    "liquidity",
                    ok,
                    f"underlying ${adv / 1e6:.0f}M ADV "
                    + ("clears" if ok else "below")
                    + f" ${floor / 1e6:.0f}M floor",
                )
            )

        spread = self._estimated_spread(inputs)
        ok = spread <= cfg.gates.max_option_spread_pct
        gates.append(
            AvoidGate(
                "option_spread",
                ok,
                f"est. option spread {spread:.1%} "
                + ("within" if ok else "exceeds")
                + f" {cfg.gates.max_option_spread_pct:.0%} ceiling",
            )
        )

        not_lottery = contract.delta >= cfg.gates.min_long_delta
        gates.append(
            AvoidGate(
                "lottery",
                not_lottery,
                f"long delta {contract.delta:.0%} "
                + ("≥" if not_lottery else "<")
                + f" {cfg.gates.min_long_delta:.0%} floor (not a lottery contract)",
            )
        )

        long_dated = contract.expiration_days >= cfg.expiration.min_dte
        gates.append(
            AvoidGate(
                "short_dated",
                long_dated,
                f"{contract.expiration_days}d expiry "
                + ("≥" if long_dated else "<")
                + f" {cfg.expiration.min_dte}d floor (avoids short-dated options)",
            )
        )
        return gates

    def _estimated_spread(self, inputs: RecommendationInputs) -> float:
        """Option bid/ask as a fraction of mid (use the override, else a proxy)."""
        if inputs.option_spread_pct is not None:
            return inputs.option_spread_pct
        b = self.config.bands
        if inputs.dollar_volume is None:
            return 0.06  # neutral assumption
        return 0.02 + 0.10 * down(inputs.dollar_volume, b.liquidity_floor, b.liquidity_good)

    # -- risk disclosures + summary ----------------------------------------- #
    def _disclosures(
        self,
        structure: OptionStructure,
        contract: ContractRecommendation,
        iv_rank: float,
        risk_budget: float,
        gates: list[AvoidGate],
    ) -> tuple[str, ...]:
        out = [
            "Research recommendation only — no live order is placed and no execution occurs.",
            "Long options/debit spreads can lose up to 100% of the premium paid; the max loss "
            "shown is your worst case.",
            "Pricing, strikes and deltas are APPROXIMATE (Brenner-Subrahmanyam vol proxy, no "
            "live chain) — verify bid/ask, open interest and greeks before trading.",
            "Time decay (theta) erodes long premium daily and accelerates as expiration nears.",
        ]
        if structure.is_spread:
            out.append(
                "Defined-risk spread: the gain is capped at the strike width minus the net debit."
            )
        else:
            out.append(
                "Single-leg long call: the entire premium is at risk if the expected move does "
                "not materialize in time."
            )
        if iv_rank >= self.config.bands.iv_high:
            out.append(
                "Implied volatility is elevated (rich premium) — long premium is exposed to an IV "
                "contraction; the spread reduces vega and cost."
            )
        if contract.contracts == 0:
            out.append(
                f"Estimated premium (${contract.est_premium_per_contract:,.0f}/contract) exceeds "
                f"the risk budget (${risk_budget:,.0f}) — reduce size or raise the budget."
            )
        blocking = [g.name for g in gates if not g.passed and g.name in _HARD_GATES]
        if blocking:
            out.append(
                "Blocked by avoid gates: "
                + ", ".join(blocking)
                + " — do not trade options on this setup as-is."
            )
        return tuple(out)

    @staticmethod
    def _summary(
        symbol: str,
        recommended: bool,
        structure: OptionStructure,
        contract: ContractRecommendation,
        gates: list[AvoidGate],
    ) -> str:
        if not recommended:
            reasons = ", ".join(g.detail for g in gates if not g.passed and g.name in _HARD_GATES)
            return f"No options recommendation for {symbol} — {reasons or 'setup not eligible'}."
        base = (
            f"{structure.display} on {symbol}: {contract.delta:.0%}Δ ~{contract.expiration_days}d"
        )
        if contract.contracts == 0:
            return (
                f"{base} — one contract (~${contract.est_premium_per_contract:,.0f}) exceeds the "
                "risk budget; reduce size or raise the budget."
            )
        rr = f"{contract.reward_to_risk:.1f}R" if contract.reward_to_risk is not None else "n/a"
        return (
            f"{base}, max loss ${contract.max_loss:,.0f}, "
            f"target ${contract.target_profit:,.0f} ({rr}), "
            f"{contract.contracts}x (~{contract.allocation_pct:.1%} of equity)."
        )
