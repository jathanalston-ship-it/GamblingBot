"""Composes the live evidence behind a trade-plan verdict.

Gathers, for one symbol: the latest scan row (price / momentum / volume /
liquidity / ATR / sector), conviction now AND at the previous scan (with
the strongest and weakest named components from the stored breakdown),
the regime, the trade plan (entry/stop/targets/RR/size + its risk, reward
and failure summaries), data freshness, days-to-earnings and the
options-eligibility verdict — then hands everything to the pure
:mod:`momentum.tradeplan.verdict` engine. Every field traces to a stored
row; missing evidence stays ``None`` and the verdict says so.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.scan_result import ScanResult
from momentum.tradeplan.verdict import Verdict, VerdictInputs, evaluate_verdict

_log = logging.getLogger(__name__)


def _factor_names(breakdown: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(strongest, weakest) component names from the stored conviction breakdown."""
    if not isinstance(breakdown, dict):
        return (), ()
    components = breakdown.get("components")
    scored: list[tuple[str, float]] = []
    if isinstance(components, dict):
        for name, value in components.items():
            if isinstance(value, (int, float)):
                scored.append((str(name).replace("_", " "), float(value)))
            elif isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
                scored.append((str(name).replace("_", " "), float(value["score"])))
    if not scored:
        return (), ()
    ordered = sorted(scored, key=lambda kv: kv[1], reverse=True)
    top = tuple(f"{name} ({score:.0f})" for name, score in ordered[:3])
    weak = tuple(f"{name} ({score:.0f})" for name, score in ordered[-2:] if score < 60)
    return top, weak


def gather_inputs(session: Session, symbol: str) -> VerdictInputs | None:
    from momentum.api import earnings_service, options_eligibility_service, tradeplan_service
    from momentum.api.services import latest_regime
    from momentum.trade_lifecycle.config import default_config as lifecycle_config

    sym = symbol.upper()
    scan = session.scalars(
        select(ScanResult)
        .where(ScanResult.symbol == sym)
        .order_by(ScanResult.as_of.desc(), ScanResult.id.desc())
        .limit(1)
    ).first()
    if scan is None:
        return None

    convictions = list(
        session.scalars(
            select(ConvictionScore)
            .where(ConvictionScore.symbol == sym)
            .order_by(ConvictionScore.as_of.desc(), ConvictionScore.id.desc())
            .limit(2)
        )
    )
    conviction = convictions[0] if convictions else None
    previous = convictions[1] if len(convictions) > 1 else None
    top, weak = _factor_names(conviction.breakdown if conviction is not None else None)

    plan = tradeplan_service.trade_plan(session, sym, None)
    regime = latest_regime(session)
    metadata = session.scalars(
        select(ScanMetadata).order_by(ScanMetadata.pull_timestamp.desc()).limit(1)
    ).first()

    days_to_earnings: int | None = None
    try:
        days_to_earnings = earnings_service.days_until_earnings(sym)
    except Exception:  # noqa: BLE001 — advisory feed; unknown stays unknown
        pass

    instrument_verdict: str | None = None
    instrument_reasons: tuple[str, ...] = ()
    try:
        eligibility = options_eligibility_service.options_eligibility(session, sym)
        if eligibility is not None:
            instrument_verdict = eligibility.recommendation
            instrument_reasons = (eligibility.summary,)
    except Exception:  # noqa: BLE001
        _log.debug("options eligibility failed for %s", sym, exc_info=True)

    plan_dict: dict[str, Any] = plan.model_dump() if plan is not None else {}
    targets = plan_dict.get("targets") or []
    first_target = targets[0].get("price") if targets else None

    return VerdictInputs(
        symbol=sym,
        price=scan.price,
        conviction_score=conviction.score if conviction is not None else None,
        conviction_band=conviction.band if conviction is not None else None,
        previous_conviction=previous.score if previous is not None else None,
        conviction_explanation=(conviction.explanation if conviction is not None else None),
        top_factors=top,
        weak_factors=weak,
        momentum_score=scan.momentum_score,
        relative_volume=scan.relative_volume,
        dollar_volume=scan.dollar_volume,
        atr=scan.atr,
        sector=scan.sector,
        sector_rs=scan.sector_rs,
        regime=regime.regime if regime is not None else None,
        regime_confidence=regime.confidence if regime is not None else None,
        data_stale=bool(metadata.stale) if metadata is not None else True,
        days_to_earnings=days_to_earnings,
        earnings_block_days=lifecycle_config().block_take_days_before_earnings,
        entry=plan.entry if plan is not None else None,
        stop=plan.stop if plan is not None else None,
        target=first_target,
        reward_risk=plan.final_reward_risk if plan is not None else None,
        suggested_shares=plan.suggested_shares if plan is not None else None,
        expected_hold_days=(
            (plan.expected_holding_days_low, plan.expected_holding_days_high)
            if plan is not None
            else (None, None)
        ),
        stop_basis="; ".join(plan_dict.get("risk_summary") or []) or None,
        target_basis="; ".join(plan_dict.get("reward_summary") or []) or None,
        size_basis=(
            f"{plan.suggested_shares} shares ≈ ${plan.suggested_risk_dollars:,.0f} at risk "
            "to the stop (the per-trade risk budget)"
            if plan is not None and plan.suggested_shares and plan.suggested_risk_dollars
            else None
        ),
        failure_conditions=tuple(plan_dict.get("failure_conditions") or []),
        instrument_verdict=instrument_verdict,
        instrument_reasons=instrument_reasons,
    )


def verdict_for(session: Session, symbol: str) -> Verdict | None:
    inputs = gather_inputs(session, symbol)
    if inputs is None:
        return None
    return evaluate_verdict(inputs)
