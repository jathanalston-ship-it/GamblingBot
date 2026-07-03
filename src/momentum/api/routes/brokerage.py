"""Brokerage endpoints — the full venue surface over HTTP.

Everything the desktop app (or any client) does against the paper brokerage
flows through these routes; there are no UI shortcuts that touch positions or
cash directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from momentum.api import brokerage_service
from momentum.brokerage import OrderRouter, PaperBrokerage
from momentum.brokerage.types import BracketSpec, ModifyTicket, OrderTicket
from momentum.core.enums import InstrumentType, OrderType, Side, TimeInForce
from momentum.core.exceptions import InvalidOrderStateError

router = APIRouter(prefix="/brokerage", tags=["brokerage"])

DEFAULT_ACCOUNT = "primary"


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def _brokerage(request: Request) -> PaperBrokerage:
    return brokerage_service.build_brokerage(_session_factory(request))


def _router(request: Request) -> OrderRouter:
    """The process-wide order router (cached — keeps the routing log alive)."""
    cached = getattr(request.app.state, "order_router", None)
    if isinstance(cached, OrderRouter):
        return cached
    built = brokerage_service.build_router(_session_factory(request))
    request.app.state.order_router = built
    return built


class BracketIn(BaseModel):
    take_profit: float | None = None
    stop_loss: float | None = None


class PlaceOrderIn(BaseModel):
    symbol: str
    side: str = "long"
    quantity: int = Field(gt=0)
    order_type: str = "market"
    time_in_force: str = "day"
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None
    trail_amount: float | None = None
    bracket: BracketIn | None = None
    oco_group: str | None = None
    instrument: str = "shares"
    multiplier: int = Field(1, ge=1)
    account_id: str = DEFAULT_ACCOUNT
    client_order_id: str | None = None
    note: str | None = None


class ModifyOrderIn(BaseModel):
    quantity: int | None = Field(None, gt=0)
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None
    trail_amount: float | None = None


class ClosePositionIn(BaseModel):
    quantity: int | None = Field(None, gt=0)
    account_id: str = DEFAULT_ACCOUNT


@router.post("/orders", status_code=201)
def place_order(body: PlaceOrderIn, request: Request) -> dict[str, Any]:
    """Place an order (idempotent per client_order_id)."""
    try:
        ticket = OrderTicket(
            client_order_id=body.client_order_id or f"api-{uuid.uuid4().hex[:12]}",
            account_id=body.account_id,
            symbol=body.symbol.upper(),
            side=Side(body.side),
            quantity=body.quantity,
            order_type=OrderType(body.order_type),
            time_in_force=TimeInForce(body.time_in_force),
            limit_price=body.limit_price,
            stop_price=body.stop_price,
            trail_percent=body.trail_percent,
            trail_amount=body.trail_amount,
            bracket=(
                BracketSpec(
                    take_profit_limit=body.bracket.take_profit,
                    stop_loss_stop=body.bracket.stop_loss,
                )
                if body.bracket is not None
                else None
            ),
            oco_group=body.oco_group,
            instrument=InstrumentType(body.instrument),
            multiplier=body.multiplier,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report = _router(request).submit(ticket)
    if not report.accepted and report.order is None:  # refused by capabilities
        raise HTTPException(status_code=422, detail=report.reason)
    assert report.order is not None
    return report.order.to_dict()


@router.delete("/orders/{order_id}")
def cancel_order(order_id: str, request: Request) -> dict[str, Any]:
    try:
        report = _router(request).cancel(order_id)
        assert report.order is not None
        return report.order.to_dict()
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/orders/{order_id}")
def modify_order(order_id: str, body: ModifyOrderIn, request: Request) -> dict[str, Any]:
    try:
        report = _router(request).modify(
            ModifyTicket(
                order_id=order_id,
                quantity=body.quantity,
                limit_price=body.limit_price,
                stop_price=body.stop_price,
                trail_percent=body.trail_percent,
                trail_amount=body.trail_amount,
            )
        )
        assert report.order is not None
        return report.order.to_dict()
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/positions/{symbol}/close")
def close_position(
    symbol: str, request: Request, body: ClosePositionIn | None = None
) -> dict[str, Any]:
    payload = body or ClosePositionIn()
    try:
        report = _router(request).close(
            payload.account_id, symbol.upper(), quantity=payload.quantity
        )
        assert report.order is not None
        return report.order.to_dict()
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/capabilities")
def get_capabilities(request: Request) -> dict[str, Any]:
    """Every registered broker's declared abilities + the routing default."""
    order_router = _router(request)
    return {
        "default": order_router.default_broker,
        "brokers": {
            name: order_router.adapter(name).capabilities.to_dict() for name in order_router.brokers
        },
    }


@router.get("/routing-log")
def get_routing_log(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    """The most recent routing decisions (accepted and refused)."""
    return _router(request).routing_log(limit)


@router.post("/tick")
def process_tick(request: Request) -> dict[str, Any]:
    """Advance the venue one tick from the freshest cached bars."""
    provider = None
    provider_factory = getattr(request.app.state, "provider_factory", None)
    if provider_factory is not None:
        provider = provider_factory()
    return brokerage_service.tick(_session_factory(request), provider=provider)


@router.get("/account")
def get_account(request: Request, account_id: str = DEFAULT_ACCOUNT) -> dict[str, Any]:
    return _brokerage(request).get_account(account_id).to_dict()


@router.get("/portfolio")
def get_portfolio(request: Request, account_id: str = DEFAULT_ACCOUNT) -> dict[str, Any]:
    return _brokerage(request).get_portfolio(account_id).to_dict()


@router.get("/buying-power")
def get_buying_power(request: Request, account_id: str = DEFAULT_ACCOUNT) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "buying_power": _brokerage(request).get_buying_power(account_id),
    }


@router.get("/positions")
def get_positions(
    request: Request, account_id: str = DEFAULT_ACCOUNT, include_closed: bool = False
) -> list[dict[str, Any]]:
    return [
        p.to_dict()
        for p in _brokerage(request).get_positions(account_id, include_closed=include_closed)
    ]


@router.get("/orders")
def get_orders(
    request: Request,
    account_id: str = DEFAULT_ACCOUNT,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return [
        o.to_dict()
        for o in _brokerage(request).get_orders(
            account_id, status=status, limit=max(1, min(limit, 500))
        )
    ]


@router.get("/orders/{order_id}")
def get_order(order_id: str, request: Request) -> dict[str, Any]:
    try:
        return _brokerage(request).get_order(order_id).to_dict()
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/fills")
def get_fills(
    request: Request, account_id: str = DEFAULT_ACCOUNT, limit: int = 100
) -> list[dict[str, Any]]:
    return [
        f.to_dict()
        for f in _brokerage(request).get_fills(account_id, limit=max(1, min(limit, 500)))
    ]


@router.get("/replay/timestamps")
def replay_timestamps(request: Request, account_id: str = DEFAULT_ACCOUNT) -> list[dict[str, Any]]:
    """Every replayable instant (account-history rows), oldest first."""
    from momentum.api import brokerage_replay_service

    return brokerage_replay_service.timestamps(_session_factory(request), account_id=account_id)


@router.get("/replay/state")
def replay_state(
    request: Request, ts: str | None = None, account_id: str = DEFAULT_ACCOUNT
) -> dict[str, Any]:
    """The venue's state at ``ts`` (ISO; defaults to now), from the immutable trail."""
    import datetime as dt

    from momentum.api import brokerage_replay_service

    if ts is None:
        when = dt.datetime.now(tz=dt.UTC)
    else:
        try:
            when = dt.datetime.fromisoformat(ts)
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.UTC)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid timestamp: {ts}") from exc
    return brokerage_replay_service.state_at(_session_factory(request), when, account_id=account_id)


@router.get("/timeline")
def timeline(
    request: Request, account_id: str = DEFAULT_ACCOUNT, limit: int = 200
) -> list[dict[str, Any]]:
    """The venue's chronological story: account events + order transitions +
    fills merged newest-first (the auto-management timeline)."""
    capped = max(1, min(limit, 1000))
    factory = _session_factory(request)
    from sqlalchemy import select

    from momentum.persistence.models.broker import (
        BrokerAccountHistory,
        BrokerFill,
        BrokerOrderEvent,
    )

    entries: list[dict[str, Any]] = []
    with factory() as session:
        for row in session.scalars(
            select(BrokerAccountHistory)
            .where(BrokerAccountHistory.account_id == account_id)
            .order_by(BrokerAccountHistory.ts.desc(), BrokerAccountHistory.id.desc())
            .limit(capped)
        ).all():
            entries.append(
                {
                    "ts": row.ts.isoformat() if row.ts else None,
                    "kind": "account",
                    "title": row.event,
                    "detail": row.detail,
                    "equity": round(row.equity, 2),
                }
            )
        for fill in session.scalars(
            select(BrokerFill)
            .where(BrokerFill.account_id == account_id)
            .order_by(BrokerFill.ts.desc(), BrokerFill.id.desc())
            .limit(capped)
        ).all():
            entries.append(
                {
                    "ts": fill.ts.isoformat() if fill.ts else None,
                    "kind": "fill",
                    "title": f"{fill.side} {fill.quantity} {fill.symbol} @ {fill.price:.2f}",
                    "detail": {"order_id": fill.order_id, "reason": fill.reason},
                    "equity": None,
                }
            )
        from momentum.persistence.models.broker import BrokerOrderRow

        order_ids = list(
            session.scalars(
                select(BrokerOrderRow.order_id)
                .where(BrokerOrderRow.account_id == account_id)
                .order_by(BrokerOrderRow.id.desc())
                .limit(200)
            ).all()
        )
        if order_ids:
            for event in session.scalars(
                select(BrokerOrderEvent)
                .where(BrokerOrderEvent.order_id.in_(order_ids))
                .order_by(BrokerOrderEvent.ts.desc(), BrokerOrderEvent.id.desc())
                .limit(capped)
            ).all():
                entries.append(
                    {
                        "ts": event.ts.isoformat() if event.ts else None,
                        "kind": "order",
                        "title": f"{event.order_id}: {event.from_status} → {event.to_status}",
                        "detail": {"reason": event.reason, "payload": event.payload},
                        "equity": None,
                    }
                )
    entries.sort(key=lambda e: e["ts"] or "", reverse=True)
    return entries[:capped]


@router.get("/portfolio-analysis")
def portfolio_analysis(request: Request, account_id: str = DEFAULT_ACCOUNT) -> dict[str, Any]:
    """The Portfolio Manager's whole-book read: exposure, concentration,
    correlation, beta, open risk, expected downside + justified suggestions."""
    from momentum.api import portfolio_manager_service

    return portfolio_manager_service.analysis_dict(_session_factory(request), account_id=account_id)


@router.get("/history")
def get_history(
    request: Request, account_id: str = DEFAULT_ACCOUNT, limit: int = 500
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = _brokerage(request).get_history(
        account_id, limit=max(1, min(limit, 2000))
    )
    return history
