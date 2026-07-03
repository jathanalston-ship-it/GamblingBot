"""The Command Center HUD — one aggregate answering the four questions.

``GET /command-center/hud`` returns, in a single round trip: the market
clock (session, countdowns, next session), the five health lights
(backend / scheduler / automation / broker / data provider), the freshest
data timestamps, the full paper-account summary (equity, cash, buying
power, P/L splits, win rate, expectancy, profit factor, largest
winner/loser, drawdown, exposure, risk used vs allowed, portfolio heat)
and the market panel (regime + confidence, breadth, index tape,
volatility). **Every number is derived from a live surface** — the paper
journal, tracked-trade marks, the ET market clock, the regime table, the
bar cache, the risk configuration. Nothing is fabricated; unknown values
are ``null``.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.trade import Trade

_log = logging.getLogger(__name__)

INDEX_SYMBOLS = ("SPY", "QQQ", "DIA", "IWM")


def _light(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _health_lights(session: Session, daemon: Any | None) -> dict[str, dict[str, str]]:
    from momentum.api import data_health_service, user_settings

    lights: dict[str, dict[str, str]] = {"backend": _light("green", "API process answering")}

    d = daemon.status() if daemon is not None and hasattr(daemon, "status") else None
    if d is None:
        lights["scheduler"] = _light("yellow", "daemon not attached (bare API session)")
    elif d.get("running") and not d.get("paused"):
        lights["scheduler"] = _light("green", f"daemon running ({d.get('cycles', 0)} cycles)")
    elif d.get("running"):
        lights["scheduler"] = _light("yellow", "daemon paused")
    else:
        lights["scheduler"] = _light("red", "daemon not running")

    autopilot = user_settings.read_autopilot()
    lights["automation"] = (
        _light("green", "Auto Pilot enabled")
        if autopilot["enabled"]
        else _light("yellow", "Auto Pilot off — monitoring only")
    )

    try:
        from momentum.api import brokerage_service

        account = brokerage_service.build_brokerage(_factory_of(session)).get_account()
        lights["broker"] = _light("green", f"paper venue answering (equity {account.equity:,.0f})")
    except Exception as exc:  # noqa: BLE001 — a dead venue is a red light, not a crash
        lights["broker"] = _light("red", f"venue error: {type(exc).__name__}")

    try:
        dh = data_health_service.data_health(session)
        by_key = {m["key"]: m for m in dh.get("metrics", [])}
        worst = "green"
        details = []
        for key in ("provider", "last_pull", "data_age"):
            metric = by_key.get(key)
            if metric is None:
                continue
            rank = {"green": 0, "yellow": 1, "red": 2}
            if rank.get(metric["status"], 0) > rank.get(worst, 0):
                worst = metric["status"]
            if metric.get("value"):
                details.append(f"{metric['label']}: {metric['value']}")
        lights["data_provider"] = _light(worst, "; ".join(details) or "no pulls recorded yet")
    except Exception as exc:  # noqa: BLE001
        lights["data_provider"] = _light("red", f"data health error: {type(exc).__name__}")
    return lights


def _factory_of(session: Session) -> Any:
    """A sessionmaker bound to this session's engine (for venue reads)."""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=session.get_bind(), future=True)


def _timestamps(session: Session) -> dict[str, str | None]:
    from momentum.persistence.models.trade_evaluation import TradeEvaluation

    metadata = session.scalars(
        select(ScanMetadata).order_by(ScanMetadata.pull_timestamp.desc()).limit(1)
    ).first()
    latest_eval = session.scalars(
        select(TradeEvaluation).order_by(TradeEvaluation.evaluated_at.desc()).limit(1)
    ).first()
    return {
        "latest_bar": metadata.bar_timestamp.isoformat()
        if metadata is not None and metadata.bar_timestamp
        else None,
        "latest_scan": metadata.pull_timestamp.isoformat() if metadata is not None else None,
        "latest_portfolio_update": (
            latest_eval.evaluated_at.isoformat()
            if latest_eval is not None and latest_eval.evaluated_at
            else None
        ),
    }


def _account(session: Session) -> dict[str, Any]:
    from momentum.api import trade_lifecycle_service, user_settings
    from momentum.api.services import performance_summary
    from momentum.risk.risk_budget_config import RiskBudgetConfig

    starting = user_settings.read_account_balance()
    trades = list(session.scalars(select(Trade)))
    open_journal = [t for t in trades if t.status == "open"]
    closed = [t for t in trades if t.status == "closed"]
    today = dt.datetime.now(tz=dt.UTC).date()
    closed_today = [t for t in closed if t.exit_ts is not None and t.exit_ts.date() == today]

    realized_total = sum(t.net_pnl or 0.0 for t in closed)
    realized_today = sum(t.net_pnl or 0.0 for t in closed_today)
    open_cost = sum(t.entry_price * t.quantity for t in open_journal)

    # Marks come from each tracked trade's latest evaluation (scan-fresh).
    # Only journal-linked rows are POSITIONS — recommendation-only tracked
    # rows (watch/track entries) carry no money and must not count.
    marks = [
        m
        for m in trade_lifecycle_service.list_trades(session, status="open", limit=500)
        if m.journal_trade_id is not None
    ]
    unrealized = sum(m.unrealized_pnl or 0.0 for m in marks if m.unrealized_pnl is not None)
    exposure = sum(
        (m.last_price or m.entry_price) * (m.quantity or 0) for m in marks if (m.quantity or 0) > 0
    )
    risk_used = sum(
        max(((m.last_price or m.entry_price) - m.stop_price), 0.0) * (m.quantity or 0)
        for m in marks
        if (m.quantity or 0) > 0
    )

    cash = starting + realized_total - open_cost
    equity = cash + exposure if marks else starting + realized_total
    heat_cap = RiskBudgetConfig().max_portfolio_heat  # the real configured ceiling

    perf = performance_summary(session)
    stats = perf.trade_stats or {}
    drawdown = (perf.performance or {}).get("max_drawdown")

    return {
        "starting_balance": starting,
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "buying_power": round(max(cash, 0.0), 2),
        "today_realized_pnl": round(realized_today, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl_total": round(realized_total, 2),
        "open_positions": len(open_journal),
        "closed_today": len(closed_today),
        "win_rate": stats.get("win_rate"),
        "avg_winner": stats.get("avg_winner_dollars"),
        "avg_loser": stats.get("avg_loser_dollars"),
        "profit_factor": stats.get("profit_factor"),
        "expectancy_r": stats.get("expectancy_r"),
        "largest_winner": stats.get("largest_winner_dollars"),
        "largest_loser": stats.get("largest_loser_dollars"),
        "max_drawdown": drawdown,
        "exposure": round(exposure, 2),
        "exposure_pct": round(exposure / equity * 100.0, 2) if equity > 0 else None,
        "risk_used": round(risk_used, 2),
        "max_risk_allowed": round(heat_cap * equity, 2) if equity > 0 else None,
        "portfolio_heat_pct": round(risk_used / equity * 100.0, 2) if equity > 0 else None,
        "heat_cap_pct": heat_cap * 100.0,
    }


def _market(session: Session) -> dict[str, Any]:
    import os

    from momentum.data.cache import BarCache
    from momentum.data.schema import Timeframe

    regime = session.scalars(
        select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)
    ).first()

    cache = BarCache(os.environ.get("MRP_BAR_CACHE", "data/bars"))
    indexes: list[dict[str, Any]] = []
    volatility: float | None = None
    for symbol in INDEX_SYMBOLS:
        try:
            if not cache.exists(symbol, Timeframe.DAY):
                continue
            frame = cache.read(symbol, Timeframe.DAY)
            if frame is None or len(frame) < 2:
                continue
            last = float(frame["close"].iloc[-1])
            prev = float(frame["close"].iloc[-2])
            indexes.append(
                {
                    "symbol": symbol,
                    "last": round(last, 2),
                    "change_pct": round((last - prev) / prev * 100.0, 2) if prev else None,
                    "as_of": str(frame.index[-1]),
                }
            )
            if symbol == "SPY" and len(frame) >= 21:
                from momentum.signals.indicators import realized_volatility

                vol = realized_volatility(frame["close"], window=20)
                value = float(vol.iloc[-1]) if vol is not None and len(vol) else float("nan")
                volatility = round(value * 100.0, 1) if value == value else None
        except Exception:  # noqa: BLE001 — a broken cache file is a missing tile, not a crash
            _log.debug("index tape read failed for %s", symbol, exc_info=True)

    # Regime label → the risk posture the UI shows.
    posture = None
    if regime is not None:
        posture = {"bullish": "risk_on", "bearish": "risk_off"}.get(regime.regime, "neutral")

    return {
        "regime": regime.regime if regime is not None else None,
        "regime_score": regime.score if regime is not None else None,
        "confidence": regime.confidence if regime is not None else None,
        "breadth_pct": (
            round(regime.breadth * 100.0, 1)
            if regime is not None and regime.breadth is not None
            else None
        ),
        "posture": posture,
        "as_of": regime.as_of.isoformat() if regime is not None else None,
        "indexes": indexes,
        "spy_realized_vol_pct": volatility,
    }


def hud(session: Session, *, daemon: Any | None = None) -> dict[str, Any]:
    from momentum.daemon.market_state import market_clock

    now = dt.datetime.now(tz=dt.UTC)
    return {
        "clock": market_clock(now).to_dict(),
        "health": _health_lights(session, daemon),
        "timestamps": _timestamps(session),
        "account": _account(session),
        "market": _market(session),
        "generated_at": now.isoformat(),
    }


def search_symbols(session: Session, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """Ticker search over what the platform actually knows: the latest scan
    rows (price/sector/momentum attached) plus the selected universe."""
    from momentum.api import universe_service
    from momentum.persistence.models.scan_result import ScanResult

    q = query.strip().upper()
    if not q:
        return []
    rows = list(
        session.scalars(
            select(ScanResult)
            .where(ScanResult.symbol.like(f"{q}%"))
            .order_by(ScanResult.as_of.desc(), ScanResult.rank.asc())
            .limit(limit * 3)
        )
    )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.symbol in seen:
            continue
        seen.add(row.symbol)
        out.append(
            {
                "symbol": row.symbol,
                "price": row.price,
                "sector": row.sector,
                "momentum_score": row.momentum_score,
                "source": "scan",
                "as_of": row.as_of.isoformat(),
            }
        )
        if len(out) >= limit:
            return out
    try:
        universe = universe_service.resolve_selected(session)
        for symbol in universe.symbols:
            if symbol.startswith(q) and symbol not in seen:
                out.append({"symbol": symbol, "source": "universe"})
                if len(out) >= limit:
                    break
    except Exception:  # noqa: BLE001 — universe resolution must not break search
        _log.debug("universe search failed", exc_info=True)
    return out
