"""Glue between the HTTP layer and the paper brokerage venue.

Builds the venue over the app's session factory and adds the one piece the
HTTP layer needs that the venue doesn't own: turning cached/live **bars**
into the :class:`~momentum.brokerage.execution_sim.Quote` objects a tick
consumes, so resting orders can trigger and fill on demand.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from momentum.brokerage import PaperBrokerage, Quote
from momentum.brokerage.router import OrderRouter
from momentum.brokerage.execution_sim import quote_from_bar
from momentum.data.cache import BarCache
from momentum.data.schema import Timeframe

_log = logging.getLogger(__name__)


def build_router(session_factory: sessionmaker[Session]) -> OrderRouter:
    """The order router with the configured venue registered.

    Today that is the internal paper venue; a live adapter registers here
    (routing configuration), never in decision code.
    """
    from momentum.api import safety_gate_service
    from momentum.brokerage import PaperBrokerAdapter

    router = OrderRouter(live_gatekeeper=safety_gate_service.build_gatekeeper(session_factory))
    router.register(PaperBrokerAdapter(build_brokerage(session_factory)), default=True)
    return router


def build_brokerage(session_factory: sessionmaker[Session]) -> PaperBrokerage:
    """The venue over the app's DB, with the user's starting balance applied.

    The Settings account balance seeds NEW brokerage accounts (an account that
    has already traded keeps its history — balances are never rewritten under
    a live book; use Settings to update an untouched account).
    """
    from momentum.api import user_settings
    from momentum.brokerage.config import default_config as brokerage_default_config

    config = brokerage_default_config()
    balance = user_settings.read_account_balance()
    if balance != config.account.starting_cash:
        config = config.model_copy(
            update={"account": config.account.model_copy(update={"starting_cash": balance})}
        )
    return PaperBrokerage(session_factory, config=config)


def quotes_for_symbols(
    symbols: list[str],
    *,
    brokerage: PaperBrokerage,
    provider: Any | None = None,
    ts: dt.datetime | None = None,
) -> dict[str, Quote]:
    """Best-effort quotes from the freshest cached (or live) daily bar."""
    when = ts or dt.datetime.now(tz=dt.UTC)
    cache = BarCache(os.environ.get("MRP_BAR_CACHE", "data/bars"))
    quotes: dict[str, Quote] = {}
    for symbol in {s.upper() for s in symbols}:
        frame = None
        try:
            if cache.exists(symbol, Timeframe.DAY):
                frame = cache.read(symbol, Timeframe.DAY)
            if (frame is None or frame.empty) and provider is not None:
                end = dt.date.today()
                frame = provider.get_bars(symbol, end - dt.timedelta(days=30), end, Timeframe.DAY)
        except Exception:  # noqa: BLE001 — a missing quote just skips the symbol
            _log.debug("no quote for %s", symbol, exc_info=True)
            continue
        if frame is None or frame.empty:
            continue
        last = frame.iloc[-1]
        quotes[symbol] = quote_from_bar(
            symbol,
            ts=when,
            close=float(last["close"]),
            volume=float(last.get("volume", 0.0)),
            high=float(last["high"]) if "high" in frame.columns else None,
            low=float(last["low"]) if "low" in frame.columns else None,
            config=brokerage.config.execution,
        )
    return quotes


def tick(
    session_factory: sessionmaker[Session],
    *,
    provider: Any | None = None,
    extra_prices: dict[str, float] | None = None,
    ts: dt.datetime | None = None,
) -> dict[str, Any]:
    """Advance the venue one tick using bar-derived quotes for every symbol
    that has an open order or an open position."""
    brokerage = build_brokerage(session_factory)
    when = ts or dt.datetime.now(tz=dt.UTC)

    from momentum.persistence.repositories.broker import (
        BrokerAccountRepository,
        BrokerOrderRepository,
        BrokerPositionRepository,
    )

    with session_factory() as session:
        symbols = {row.symbol for row in BrokerOrderRepository(session).open_orders()}
        for account in BrokerAccountRepository(session).all_accounts():
            symbols.update(
                p.symbol
                for p in BrokerPositionRepository(session).open_for_account(account.account_id)
            )

    quotes = quotes_for_symbols(sorted(symbols), brokerage=brokerage, provider=provider, ts=when)
    # Freshest intraday prints (e.g. from the daemon's minute pulls) override
    # the bar-derived last while keeping the modeled spread width.
    for symbol, price in (extra_prices or {}).items():
        sym = symbol.upper()
        base = quotes.get(sym)
        if base is not None and price > 0:
            half = base.spread / 2.0
            quotes[sym] = Quote(
                symbol=sym,
                ts=when,
                bid=max(price - half, 0.01),
                ask=price + half,
                last=price,
                volume=base.volume,
                day_range_pct=base.day_range_pct,
                estimated=True,
            )

    result = brokerage.process_tick(quotes, ts=when)
    result["symbols"] = sorted(quotes)

    # Verify the venue's word against the immutable fills trail while the
    # book is warm — discrepancies surface immediately, not at end of day.
    try:
        from momentum.brokerage import Reconciler

        report = Reconciler(session_factory, brokerage).reconcile(ts=when)
        result["reconciliation"] = {
            "clean": report.clean,
            "discrepancies": len(report.discrepancies),
            "corrections": report.corrections,
        }
    except Exception:  # noqa: BLE001 — reconciliation must never break a tick
        _log.warning("post-tick reconciliation failed", exc_info=True)
    return result
