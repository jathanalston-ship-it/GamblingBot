"""The "Today" aggregate — everything the home screen needs, in plain terms.

One read-only round trip answering the four questions a trader opens the app
with: *Is it OK to buy? What do I own and how is it doing? What should I buy
today? What did the app do?* — plus the evidence behind the rules. Every field
is derived from a stored row (scan results, trade plans, the journal, the
regime row's market gate, alerts, the latest backtest); nothing is invented and
nothing is written.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from momentum.api import hud_service, services, strategy_service, trade_lifecycle_service
from momentum.persistence.models.alert import Alert
from momentum.persistence.models.optimization_result import OptimizationResult
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.scan_rejection import ScanRejection
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.trade import Trade
from momentum.persistence.models.trade_plan import TradePlan
from momentum.strategy import StrategyConfig, default_config

#: Alert kinds a trader acts on (the home feed hides everything else).
IMPORTANT_ALERTS = (
    "trade_managed",
    "autopilot_entry",
    "market_gate",
    "new_signal",
    "stop_reached",
)
BACKTEST_STUDY = "momentum_breakout"


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    return aware.isoformat()


def _data(session: Session, run_id: str | None) -> dict[str, Any]:
    meta = session.scalars(
        select(ScanMetadata).order_by(ScanMetadata.pull_timestamp.desc()).limit(1)
    ).first()
    if meta is None:
        return {"has_scan": False, "stale": False, "run_id": run_id}
    return {
        "has_scan": True,
        "run_id": run_id,
        "provider": meta.provider,
        "universe": meta.universe,
        "symbols": meta.symbol_count,
        "bars_through": _iso(meta.bar_timestamp),
        "last_scan_at": _iso(meta.pull_timestamp),
        "stale": bool(meta.stale),
    }


def _positions(session: Session) -> list[dict[str, Any]]:
    """Open paper positions (journal-linked tracked trades), newest first."""
    out: list[dict[str, Any]] = []
    now = dt.datetime.now(tz=dt.UTC)
    for row in trade_lifecycle_service.list_trades(session, status="open", limit=500):
        if row.journal_trade_id is None:
            continue  # a recommendation, not a position
        journal = session.get(Trade, row.journal_trade_id)
        if journal is None or journal.status != "open":
            continue
        shares = int(journal.quantity)
        entry = float(journal.entry_price)
        last = row.last_price if row.last_price is not None else entry
        stop = journal.current_stop if journal.current_stop is not None else row.stop_price
        initial_risk = entry - row.stop_price
        entered = journal.entry_ts
        if entered is not None and entered.tzinfo is None:
            entered = entered.replace(tzinfo=dt.UTC)
        exit_level = row.exit_level
        if exit_level is None:
            # Not evaluated yet (bought since the last scan): the scan row that
            # produced the signal already carries the level.
            exit_level = session.scalar(
                select(ScanResult.exit_level)
                .where(ScanResult.symbol == row.symbol, ScanResult.exit_level.is_not(None))
                .order_by(ScanResult.as_of.desc(), ScanResult.id.desc())
                .limit(1)
            )
        # The level that actually ends the trade next: the higher of the two.
        sell_below = max(stop, exit_level) if exit_level is not None else stop
        out.append(
            {
                "trade_uid": row.trade_uid,
                "symbol": row.symbol,
                "sector": row.sector,
                "shares": shares,
                "entry_price": round(entry, 2),
                "last_price": round(float(last), 2),
                "value": round(float(last) * shares, 2),
                "pnl": round((float(last) - entry) * shares, 2),
                "pnl_pct": round((float(last) / entry - 1.0) * 100.0, 2) if entry > 0 else None,
                "r": round((float(last) - entry) / initial_risk, 2) if initial_risk > 0 else None,
                "stop": round(float(stop), 2),
                "exit_level": round(float(exit_level), 2) if exit_level is not None else None,
                "sell_below": round(float(sell_below), 2),
                "room_pct": (
                    round((float(last) / sell_below - 1.0) * 100.0, 1) if sell_below > 0 else None
                ),
                "risk_dollars": round(max(float(last) - float(stop), 0.0) * shares, 2),
                "days_held": (max(0, (now - entered).days) if entered is not None else None),
                "entered_at": _iso(entered),
                "mode": row.management_mode,
                "entry_reason": journal.entry_reason,
            }
        )
    out.sort(key=lambda p: p["entered_at"] or "", reverse=True)
    return out


def _signals(
    session: Session, run_id: str | None, held: set[str], strategy: StrategyConfig
) -> list[dict[str, Any]]:
    """Today's buy signals: the active scan's candidates with their plans."""
    if run_id is None:
        return []
    plans = {
        p.symbol: p for p in session.scalars(select(TradePlan).where(TradePlan.run_id == run_id))
    }
    out: list[dict[str, Any]] = []
    rows = session.scalars(
        select(ScanResult)
        .where(ScanResult.run_id == run_id, ScanResult.passed.is_(True))
        .order_by(ScanResult.rank.asc())
    )
    for row in rows:
        plan = plans.get(row.symbol)
        entry = plan.entry if plan is not None else row.price
        stop = plan.stop if plan is not None else None
        shares = plan.suggested_shares if plan is not None else None
        risk_per_share = (entry - stop) if entry is not None and stop is not None else None
        out.append(
            {
                "symbol": row.symbol,
                "sector": row.sector,
                "rank": row.rank,
                "price": round(row.price, 2) if row.price is not None else None,
                "momentum_pct": (
                    round(row.momentum_score, 0) if row.momentum_score is not None else None
                ),
                "bars_since_breakout": row.bars_since_breakout,
                "breakout_level": (
                    round(row.breakout_level, 2) if row.breakout_level is not None else None
                ),
                "entry": round(entry, 2) if entry is not None else None,
                "stop": round(stop, 2) if stop is not None else None,
                "stop_pct": (
                    round((entry - stop) / entry * 100.0, 1)
                    if entry and stop is not None and entry > 0
                    else None
                ),
                "exit_level": round(row.exit_level, 2) if row.exit_level is not None else None,
                "shares": shares,
                "position_value": (
                    round(shares * entry, 2) if shares and entry is not None else None
                ),
                "risk_dollars": (
                    round(shares * risk_per_share, 2)
                    if shares and risk_per_share is not None
                    else None
                ),
                "held": row.symbol in held,
                "why": _why(row, strategy),
            }
        )
    return out


def _why(row: ScanResult, strategy: StrategyConfig) -> str:
    parts: list[str] = []
    if row.momentum_score is not None:
        parts.append(f"stronger than {row.momentum_score:.0f}% of the universe")
    if row.bars_since_breakout is not None:
        when = (
            "on the last session"
            if row.bars_since_breakout == 0
            else f"{row.bars_since_breakout} session{'s' if row.bars_since_breakout != 1 else ''} ago"
        )
        parts.append(f"new {strategy.breakout_lookback}-day high {when}")
    if row.trend_ma is not None and row.price is not None and row.trend_ma > 0:
        parts.append(
            f"{(row.price / row.trend_ma - 1.0) * 100.0:.0f}% above its "
            f"{strategy.trend_ma_period}-day average"
        )
    return "; ".join(parts)


def _watching(session: Session, run_id: str | None) -> list[str]:
    """Leaders in an uptrend that have not broken out yet (next in line)."""
    if run_id is None:
        return []
    rows = session.scalars(
        select(ScanRejection.symbol)
        .where(ScanRejection.run_id == run_id, ScanRejection.reason == "no_breakout")
        .order_by(ScanRejection.symbol.asc())
    )
    return [str(symbol) for symbol in rows]


def _closed_count(session: Session) -> int:
    return int(
        session.scalar(select(func.count()).select_from(Trade).where(Trade.status == "closed")) or 0
    )


def _activity(session: Session, limit: int = 12) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(Alert)
        .where(Alert.kind.in_(IMPORTANT_ALERTS))
        .order_by(Alert.ts.desc(), Alert.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": a.id,
            "ts": _iso(a.ts),
            "kind": a.kind,
            "symbol": a.symbol,
            "severity": a.severity,
            "title": a.title,
            "description": a.description,
        }
        for a in rows
    ]


def evidence(session: Session) -> dict[str, Any] | None:
    """The latest backtest of the live strategy (None until one has been run)."""
    row = session.scalars(
        select(OptimizationResult)
        .where(OptimizationResult.study_name == BACKTEST_STUDY, OptimizationResult.sample == "full")
        .order_by(OptimizationResult.id.desc())
        .limit(1)
    ).first()
    if row is None or not isinstance(row.details, dict):
        return None
    scorecard = row.details.get("scorecard")
    if not isinstance(scorecard, dict):
        return None
    params = row.parameters if isinstance(row.parameters, dict) else {}
    return {
        "run_id": row.run_id,
        "symbols": params.get("symbols"),
        "config_hash": params.get("config_hash"),
        "matches_live_rules": params.get("config_hash") == default_config().config_hash(),
        **scorecard,
    }


def today(session: Session, *, daemon: Any | None = None) -> dict[str, Any]:
    """The home-screen aggregate."""
    from momentum.api import autopilot_service, user_settings

    strategy = default_config()
    run_id = services.resolve_active_run_id(session)
    gate = strategy_service.market_gate(session, strategy)
    positions = _positions(session)
    held = {p["symbol"] for p in positions}
    signals = _signals(session, run_id, held, strategy)
    account = hud_service._account(session)
    autopilot_settings = user_settings.read_autopilot()
    max_positions = int(autopilot_settings["max_open_positions"])  # type: ignore[call-overload]
    bot = autopilot_service.status(session, daemon=daemon)
    data = _data(session, run_id)

    open_signals = [s for s in signals if not s["held"]]
    if not data["has_scan"]:
        headline = "No scan yet — press Scan now to load today's market."
    elif data["stale"]:
        headline = "Market data is out of date — scan again before acting."
    elif not gate.entries_allowed:
        headline = gate.headline + "."
    elif not open_signals:
        headline = "No new buy signals today — nothing to do but manage what you hold."
    elif len(positions) >= max_positions:
        headline = f"The book is full ({len(positions)} positions) — no new buys until one closes."
    else:
        n = len(open_signals)
        headline = f"{n} buy signal{'s' if n != 1 else ''} today."

    return {
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "headline": headline,
        "market": gate.to_dict(),
        "data": data,
        "account": {
            **account,
            "closed_trades": _closed_count(session),
            "max_positions": max_positions,
            "slots_free": max(0, max_positions - len(positions)),
        },
        "positions": positions,
        "signals": signals,
        "watching": _watching(session, run_id),
        "autopilot": {
            "enabled": bool(autopilot_settings["enabled"]),
            "state": bot["state"],
            "state_label": bot["state_label"],
            "activity": bot["activity"],
            "next_action": bot["next_action"],
            "market_state": bot["market_state"],
            "last_error": bot["last_error"],
        },
        "activity": _activity(session),
        "evidence": evidence(session),
        "rules": strategy_service.rules_summary(strategy),
    }
