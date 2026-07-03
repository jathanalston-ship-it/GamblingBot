"""Shadow Trading Mode — generate orders, never submit them, grade the idea.

Wired as the final optional step of every fresh scan (mirroring autopilot's
selection and restraint so the ledger records what the strategy *would*
do), plus read endpoints for the ledger and the 60-trading-day report.
Shadow rows live in their own table and never touch the paper journal,
the brokerage venue, or any live broker — ``orders_submitted`` is zero by
construction.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from momentum.core.enums import Side
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.shadow_trade import ShadowTrade
from momentum.persistence.models.trade_plan import TradePlan
from momentum.shadow import expected_fill, manage_shadow_trade, shadow_report
from momentum.shadow.config import ShadowConfig, default_config

_log = logging.getLogger(__name__)

DEFAULT_QUANTITY = 100


def _bar_values(frame: pd.DataFrame | None) -> tuple[float, float, float | None, float | None]:
    """(close, volume, high, low) of the newest bar."""
    assert frame is not None and not frame.empty
    row = frame.iloc[-1]
    return (
        float(row["close"]),
        float(row.get("volume", 0.0)),
        float(row["high"]) if "high" in row else None,
        float(row["low"]) if "low" in row else None,
    )


def _plan_for(session: Session, run_id: str, symbol: str) -> TradePlan | None:
    return session.scalars(
        select(TradePlan).where(TradePlan.run_id == run_id, TradePlan.symbol == symbol).limit(1)
    ).first()


def _target_from_plan(plan: TradePlan) -> float | None:
    payload = plan.plan or {}
    targets = payload.get("targets")
    if isinstance(targets, list) and targets and isinstance(targets[0], dict):
        price = targets[0].get("price")
        if isinstance(price, (int, float)):
            return float(price)
    if plan.risk_per_share:
        return plan.entry + 2.0 * plan.risk_per_share  # honest 2R fallback
    return None


def run_for_scan(
    session: Session,
    *,
    run_id: str,
    ts: dt.datetime,
    market_state: str | None,
    bars: Mapping[str, pd.DataFrame] | None = None,
    intraday_prices: Mapping[str, float] | None = None,
    config: ShadowConfig | None = None,
) -> dict[str, Any]:
    """Manage the open shadow book, then generate this cycle's shadow entries."""
    from momentum.api import user_settings

    result: dict[str, Any] = {"enabled": user_settings.read_shadow()["enabled"]}
    if not result["enabled"]:
        return result
    cfg = config or default_config()
    frames = bars or {}
    intraday = intraday_prices or {}

    managed = closed = 0
    open_rows = list(session.scalars(select(ShadowTrade).where(ShadowTrade.status == "open")).all())
    for row in open_rows:
        frame = frames.get(row.symbol)
        price = intraday.get(row.symbol)
        if price is None and frame is not None and not frame.empty:
            price = float(frame["close"].iloc[-1])
        if price is None:
            continue  # no data this cycle — never guess

        row.last_price = price
        row.last_eval_at = ts
        row.evaluations += 1
        row.mfe_price = max(row.mfe_price or price, price)
        row.mae_price = min(row.mae_price or price, price)
        managed += 1

        action = manage_shadow_trade(
            price=price,
            entry=row.expected_entry,
            stop=row.stop_price,
            current_stop=row.current_stop,
            target=row.target_price,
            config=cfg,
        )
        if action.kind == "raise_stop" and action.new_stop is not None:
            row.current_stop = action.new_stop
        elif action.closes:
            close_v = price
            volume = 0.0
            high = low = None
            if frame is not None and not frame.empty:
                close_v, volume, high, low = _bar_values(frame)
            fill = expected_fill(
                symbol=row.symbol,
                side=Side.SHORT,
                quantity=row.quantity,
                ts=ts,
                close=price if price != close_v else close_v,
                volume=volume,
                high=high,
                low=low,
            )
            row.status = "closed"
            row.closed_at = ts
            row.exit_run_id = run_id
            row.expected_exit = fill.price
            row.reference_exit = fill.reference
            row.exit_slippage_bps = fill.slippage_bps
            row.exit_reason = action.exit_reason
            row.expected_pnl = (fill.price - row.expected_entry) * row.quantity
            risk = row.expected_entry - row.stop_price
            row.expected_r = (fill.price - row.expected_entry) / risk if risk > 0 else None
            closed += 1

    entered = 0
    if (market_state or "unknown") == "regular":
        open_symbols = {
            r.symbol
            for r in session.scalars(select(ShadowTrade).where(ShadowTrade.status == "open")).all()
        }
        # One shadow row per (run, symbol): a symbol closed earlier in this
        # same run is not re-entered (and the unique key enforces it).
        this_run = set(
            session.scalars(select(ShadowTrade.symbol).where(ShadowTrade.run_id == run_id)).all()
        )
        held = open_symbols | this_run
        slots = cfg.max_open_positions - len(open_symbols)
        candidates = list(
            session.scalars(
                select(ConvictionScore)
                .where(
                    ConvictionScore.run_id == run_id,
                    ConvictionScore.score >= cfg.min_conviction_score,
                )
                .order_by(ConvictionScore.score.desc())
            ).all()
        )
        budget = min(cfg.max_entries_per_cycle, max(slots, 0))
        for candidate in candidates:
            if entered >= budget:
                break
            symbol = candidate.symbol
            if symbol in held:
                continue
            plan = _plan_for(session, run_id, symbol)
            frame = frames.get(symbol)
            if plan is None or frame is None or frame.empty:
                continue  # no plan or no data — nothing honest to record
            close, volume, high, low = _bar_values(frame)
            reference = intraday.get(symbol, close)
            quantity = plan.suggested_shares or DEFAULT_QUANTITY
            fill = expected_fill(
                symbol=symbol,
                side=Side.LONG,
                quantity=quantity,
                ts=ts,
                close=reference,
                volume=volume,
                high=high,
                low=low,
            )
            session.add(
                ShadowTrade(
                    symbol=symbol,
                    run_id=run_id,
                    entered_at=ts,
                    quantity=quantity,
                    conviction_score=float(candidate.score),
                    expected_entry=fill.price,
                    reference_entry=fill.reference,
                    entry_slippage_bps=fill.slippage_bps,
                    stop_price=plan.stop,
                    target_price=_target_from_plan(plan),
                    mfe_price=fill.price,
                    mae_price=fill.price,
                    last_price=reference,
                    last_eval_at=ts,
                )
            )
            held.add(symbol)
            entered += 1

    session.commit()
    result.update({"managed": managed, "closed": closed, "entered": entered})
    return result


def report(
    session: Session, *, now: dt.datetime | None = None, config: ShadowConfig | None = None
) -> dict[str, Any]:
    cfg = config or default_config()
    when = now or dt.datetime.now(tz=dt.UTC)
    # A generous calendar window that always covers the trading-day window.
    window_start = when - dt.timedelta(days=int(cfg.window_trading_days * 1.6) + 7)

    rows = [
        r.to_dict()
        for r in session.scalars(
            select(ShadowTrade)
            .where(ShadowTrade.entered_at >= window_start)
            .order_by(ShadowTrade.entered_at)
        )
    ]
    candidates = (
        session.execute(
            select(func.count(ConvictionScore.id)).where(
                ConvictionScore.created_at >= window_start,
                ConvictionScore.score >= cfg.min_conviction_score,
            )
        ).scalar_one()
        or 0
    )
    return shadow_report(rows, now=when, candidates_seen=int(candidates), config=cfg)


def trades(
    session: Session, *, status: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    query = select(ShadowTrade).order_by(ShadowTrade.entered_at.desc()).limit(limit)
    if status:
        query = query.where(ShadowTrade.status == status)
    return [r.to_dict() for r in session.scalars(query)]
