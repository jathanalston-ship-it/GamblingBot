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
from momentum.brokerage import PaperBrokerage
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
    view = _brokerage(request).place_order(ticket)
    return view.to_dict()


@router.delete("/orders/{order_id}")
def cancel_order(order_id: str, request: Request) -> dict[str, Any]:
    try:
        return _brokerage(request).cancel_order(order_id).to_dict()
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/orders/{order_id}")
def modify_order(order_id: str, body: ModifyOrderIn, request: Request) -> dict[str, Any]:
    try:
        return (
            _brokerage(request)
            .modify_order(
                ModifyTicket(
                    order_id=order_id,
                    quantity=body.quantity,
                    limit_price=body.limit_price,
                    stop_price=body.stop_price,
                    trail_percent=body.trail_percent,
                    trail_amount=body.trail_amount,
                )
            )
            .to_dict()
        )
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/positions/{symbol}/close")
def close_position(
    symbol: str, request: Request, body: ClosePositionIn | None = None
) -> dict[str, Any]:
    payload = body or ClosePositionIn()
    try:
        return (
            _brokerage(request)
            .close_position(payload.account_id, symbol.upper(), quantity=payload.quantity)
            .to_dict()
        )
    except InvalidOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/history")
def get_history(
    request: Request, account_id: str = DEFAULT_ACCOUNT, limit: int = 500
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = _brokerage(request).get_history(
        account_id, limit=max(1, min(limit, 2000))
    )
    return history
