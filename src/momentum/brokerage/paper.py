"""PaperBrokerage — the first (simulated) implementation of the Brokerage.

A complete venue over the ``broker_*`` tables: accounts with T+n settlement
and margin-aware buying power, the full order-management system (market /
limit / stop / stop-limit / trailing-stop / bracket / OCO, every lifecycle
transition persisted append-only), and realistic execution via
:class:`~momentum.brokerage.execution_sim.ExecutionSimulator`.

Everything flows through :class:`PaperBrokerage` — there are no shortcuts
that mutate positions or cash directly. Market data arrives through
:meth:`process_tick` (the daemon/scan loop feeds it quotes); resting orders
trigger, ratchet and fill there.

Design notes:

* **Idempotent placement** — ``client_order_id`` is the key; re-submitting
  returns the existing order.
* **Brackets** — child take-profit/stop-loss orders are created ``SUBMITTED``
  and only start ``WORKING`` when the entry fills. One child's fill cancels
  the other (they share an OCO group).
* **Settlement** — sale proceeds are unsettled for ``settlement_days``
  business days; only settled cash counts toward buying power.
* **History** — every material change appends a ``broker_account_history``
  row; the repository refuses deletes.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from momentum.brokerage.accounts import (
    PendingSettlement,
    compute_account_metrics,
    settlement_time,
    split_settled,
)
from momentum.brokerage.config import BrokerageConfig, default_config
from momentum.brokerage.execution_sim import ExecutionSimulator, Quote
from momentum.brokerage.oms import BrokerOrder, OrderLink
from momentum.brokerage.types import (
    AccountView,
    FillView,
    ModifyTicket,
    OrderTicket,
    OrderView,
    PortfolioView,
    PositionView,
)
from momentum.core.enums import InstrumentType, OrderStatus, OrderType, Side, TimeInForce
from momentum.core.exceptions import InvalidOrderStateError
from momentum.persistence.models.broker import (
    BrokerAccount,
    BrokerAccountHistory,
    BrokerFill,
    BrokerOrderEvent,
    BrokerOrderRow,
    BrokerPosition,
)
from momentum.persistence.repositories.broker import (
    BrokerAccountHistoryRepository,
    BrokerAccountRepository,
    BrokerFillRepository,
    BrokerOrderEventRepository,
    BrokerOrderRepository,
    BrokerPositionRepository,
)

_log = logging.getLogger(__name__)

DEFAULT_ACCOUNT_ID = "primary"

_OPEN_STATUSES = ("submitted", "accepted", "working", "partially_filled")


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


class PaperBrokerage:
    """The simulated venue (implements :class:`momentum.brokerage.Brokerage`)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        config: BrokerageConfig | None = None,
        clock: Callable[[], dt.datetime] = _now,
    ) -> None:
        self._session_factory = session_factory
        self.config = config or default_config()
        self.simulator = ExecutionSimulator(self.config.execution)
        self._clock = clock

    @property
    def name(self) -> str:
        return "paper"

    # ------------------------------------------------------------------ #
    # accounts
    # ------------------------------------------------------------------ #
    def ensure_account(
        self, account_id: str = DEFAULT_ACCOUNT_ID, *, name: str | None = None
    ) -> None:
        """Create the account on first use (idempotent)."""
        with self._session_factory() as session:
            self._ensure_account(session, account_id, name=name)
            session.commit()

    def _ensure_account(
        self, session: Session, account_id: str, *, name: str | None = None
    ) -> BrokerAccount:
        repo = BrokerAccountRepository(session)
        account = repo.by_account_id(account_id)
        if account is not None:
            return account
        cfg = self.config.account
        account = BrokerAccount(
            account_id=account_id,
            name=name or "Paper Account",
            starting_cash=cfg.starting_cash,
            cash=cfg.starting_cash,
            margin_multiplier=cfg.margin_multiplier,
            settlement_days=cfg.settlement_days,
            pending_settlements=[],
        )
        repo.add(account)
        session.flush()
        self._append_history(session, account, event="opened", ts=self._clock(), detail=None)
        return account

    # ------------------------------------------------------------------ #
    # Brokerage protocol — trading
    # ------------------------------------------------------------------ #
    def place_order(self, ticket: OrderTicket, *, ts: dt.datetime | None = None) -> OrderView:
        when = ts or self._clock()
        with self._session_factory() as session:
            self._roll_day(session, ticket.account_id, when)
            orders = BrokerOrderRepository(session)
            existing = orders.by_order_id(ticket.client_order_id)
            if existing is not None:  # idempotent re-submit
                return self._order_view(session, existing)

            account = self._ensure_account(session, ticket.account_id)
            order = BrokerOrder.from_ticket(ticket, ts=when)

            reason = self._validate(session, account, order, ticket)
            if reason is not None:
                order.reject(reason, ts=when)
            else:
                order.accept(ts=when)
                order.work(ts=when)

            try:
                row = self._persist_new_order(session, order)
                if reason is None and ticket.bracket is not None and not ticket.bracket.is_empty:
                    self._create_bracket_children(session, order, ticket, ts=when)
                session.commit()
            except IntegrityError:
                # Two threads raced the same client_order_id past the
                # idempotency read: the unique index kept exactly one row —
                # return it, so a duplicate submission can never double-order.
                session.rollback()
                winner = orders.by_order_id(ticket.client_order_id)
                if winner is not None:
                    return self._order_view(session, winner)
                raise
            return self._order_view(session, row)

    def cancel_order(self, order_id: str, *, ts: dt.datetime | None = None) -> OrderView:
        when = ts or self._clock()
        with self._session_factory() as session:
            row = self._require_order(session, order_id)
            order = self._hydrate(row)
            order.cancel("cancelled by request", ts=when)
            self._sync_row(session, row, order)
            self._cancel_children(session, row.order_id, when, "parent order cancelled")
            session.commit()
            return self._order_view(session, row)

    def modify_order(self, ticket: ModifyTicket, *, ts: dt.datetime | None = None) -> OrderView:
        when = ts or self._clock()
        with self._session_factory() as session:
            row = self._require_order(session, ticket.order_id)
            order = self._hydrate(row)
            order.modify(
                ts=when,
                quantity=ticket.quantity,
                limit_price=ticket.limit_price,
                stop_price=ticket.stop_price,
                trail_percent=ticket.trail_percent,
                trail_amount=ticket.trail_amount,
            )
            self._sync_row(session, row, order)
            session.commit()
            return self._order_view(session, row)

    def close_position(
        self,
        account_id: str,
        symbol: str,
        *,
        quantity: int | None = None,
        ts: dt.datetime | None = None,
    ) -> OrderView:
        when = ts or self._clock()
        with self._session_factory() as session:
            position = BrokerPositionRepository(session).open_position(account_id, symbol)
            if position is None or position.quantity <= 0:
                raise InvalidOrderStateError(f"no open position in {symbol.upper()}")
            qty = min(quantity or position.quantity, position.quantity)
            exit_side = Side.SHORT if position.side == Side.LONG.value else Side.LONG
            instrument = InstrumentType(position.instrument)
        ticket = OrderTicket(
            client_order_id=f"close-{symbol.upper()}-{uuid.uuid4().hex[:10]}",
            account_id=account_id,
            symbol=symbol.upper(),
            side=exit_side,
            quantity=qty,
            order_type=OrderType.MARKET,
            instrument=instrument,
            multiplier=position.multiplier,
            note="close position",
        )
        return self.place_order(ticket, ts=when)

    # ------------------------------------------------------------------ #
    # market data — resting orders trigger and fill here
    # ------------------------------------------------------------------ #
    def process_tick(
        self, quotes: Mapping[str, Quote], *, ts: dt.datetime | None = None
    ) -> dict[str, Any]:
        """Advance the venue one tick: expiry, triggers, ratchets, fills, marks."""
        when = ts or self._clock()
        filled = 0
        expired = 0
        with self._session_factory() as session:
            orders_repo = BrokerOrderRepository(session)
            for row in orders_repo.open_orders():
                self._roll_day(session, row.account_id, when)
                quote = quotes.get(row.symbol)
                order = self._hydrate(row)

                if self._expire_if_due(session, row, order, when):
                    expired += 1
                    continue
                if quote is None or row.status == "submitted":
                    continue  # bracket children wait for the entry; no data = no action

                order.ratchet_trail(quote.last)
                if self._should_execute(order, quote):
                    if self._execute(session, row, order, quote, when):
                        filled += 1
                else:
                    self._sync_row(session, row, order)  # persist any ratchet move

            self._mark_positions(session, quotes, when)
            session.commit()
        return {"filled": filled, "expired": expired, "quotes": len(quotes)}

    # ------------------------------------------------------------------ #
    # Brokerage protocol — reads
    # ------------------------------------------------------------------ #
    def get_account(self, account_id: str = DEFAULT_ACCOUNT_ID) -> AccountView:
        with self._session_factory() as session:
            account = self._ensure_account(session, account_id)
            view = self._account_view(session, account)
            session.commit()
            return view

    def get_portfolio(self, account_id: str = DEFAULT_ACCOUNT_ID) -> PortfolioView:
        with self._session_factory() as session:
            account = self._ensure_account(session, account_id)
            positions = tuple(
                self._position_view(p)
                for p in BrokerPositionRepository(session).open_for_account(account_id)
            )
            open_orders = tuple(
                self._order_view(session, row, with_events=False)
                for row in BrokerOrderRepository(session).for_account(
                    account_id, statuses=list(_OPEN_STATUSES), limit=200
                )
            )
            view = PortfolioView(
                account=self._account_view(session, account),
                positions=positions,
                open_orders=open_orders,
            )
            session.commit()
            return view

    def get_buying_power(self, account_id: str = DEFAULT_ACCOUNT_ID) -> float:
        return self.get_account(account_id).buying_power

    def get_positions(
        self, account_id: str = DEFAULT_ACCOUNT_ID, *, include_closed: bool = False
    ) -> list[PositionView]:
        with self._session_factory() as session:
            repo = BrokerPositionRepository(session)
            rows = (
                repo.all_for_account(account_id)
                if include_closed
                else repo.open_for_account(account_id)
            )
            return [self._position_view(p) for p in rows]

    def get_orders(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OrderView]:
        statuses: list[str] | None = None
        if status == "open":
            statuses = list(_OPEN_STATUSES)
        elif status == "terminal":
            statuses = ["filled", "cancelled", "rejected", "expired"]
        elif status:
            statuses = [status]
        with self._session_factory() as session:
            rows = BrokerOrderRepository(session).for_account(
                account_id, statuses=statuses, limit=limit
            )
            return [self._order_view(session, row, with_events=False) for row in rows]

    def get_order(self, order_id: str) -> OrderView:
        with self._session_factory() as session:
            return self._order_view(session, self._require_order(session, order_id))

    def get_fills(
        self, account_id: str = DEFAULT_ACCOUNT_ID, *, limit: int = 100
    ) -> list[FillView]:
        with self._session_factory() as session:
            return [
                FillView(
                    fill_id=f.id,
                    order_id=f.order_id,
                    account_id=f.account_id,
                    symbol=f.symbol,
                    side=Side(f.side),
                    quantity=f.quantity,
                    price=f.price,
                    fees=f.fees,
                    ts=f.ts,
                )
                for f in BrokerFillRepository(session).for_account(account_id, limit=limit)
            ]

    def get_history(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
        *,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = BrokerAccountHistoryRepository(session).for_account(
                account_id, start=start, end=end, limit=limit
            )
            return [r.to_dict() for r in rows]

    # ------------------------------------------------------------------ #
    # internals — validation
    # ------------------------------------------------------------------ #
    def _validate(
        self,
        session: Session,
        account: BrokerAccount,
        order: BrokerOrder,
        ticket: OrderTicket,
    ) -> str | None:
        """Return a rejection reason, or ``None`` when the order is acceptable."""
        orders = BrokerOrderRepository(session)
        if len(orders.open_orders(account.account_id)) >= self.config.orders.max_open_orders:
            return f"too many open orders (max {self.config.orders.max_open_orders})"

        positions = BrokerPositionRepository(session)
        position = positions.open_position(
            account.account_id, order.symbol, instrument=order.instrument.value
        )
        held = position.quantity if position is not None and position.side == "long" else 0

        if order.side is Side.LONG:
            # Entry (or add): needs buying power for the estimated cost.
            reference = ticket.limit_price or ticket.stop_price
            if reference is None:
                last = positions.open_position(account.account_id, order.symbol)
                reference = last.last_price if last is not None else None
            if reference is None:
                # No price reference at all — accept; the tick-time execution
                # re-checks affordability against the real quote.
                return None
            cost = reference * order.quantity * order.multiplier
            buying_power = self._buying_power(account)
            if cost > buying_power:
                return (
                    f"insufficient buying power: need ~{cost:,.0f}, "
                    f"have {buying_power:,.0f} settled"
                )
            return None

        # Selling: no naked shorts in the simulation — must hold the shares
        # (bracket children are exempt while their entry is still working).
        if order.link.parent_order_id is not None:
            return None
        if order.quantity > held:
            return f"cannot sell {order.quantity} {order.symbol}: holding {held}"
        return None

    def _buying_power(self, account: BrokerAccount) -> float:
        pending = _pending_from_json(account.pending_settlements)
        settled, _unsettled, _ = split_settled(account.cash, pending, self._clock())
        return max(settled, 0.0) * account.margin_multiplier

    # ------------------------------------------------------------------ #
    # internals — order execution
    # ------------------------------------------------------------------ #
    def _should_execute(self, order: BrokerOrder, quote: Quote) -> bool:
        if order.order_type is OrderType.MARKET:
            return True
        if order.order_type is OrderType.LIMIT:
            return order.marketable_limit(quote.bid, quote.ask)
        if order.order_type in (OrderType.STOP, OrderType.TRAILING_STOP):
            return order.is_triggered(quote.last)
        if order.order_type is OrderType.STOP_LIMIT:
            return order.is_triggered(quote.last) and order.marketable_limit(quote.bid, quote.ask)
        return False

    def _execute(
        self,
        session: Session,
        row: BrokerOrderRow,
        order: BrokerOrder,
        quote: Quote,
        when: dt.datetime,
    ) -> bool:
        """Run the simulator for one tick; apply fills; handle links. True on fill."""
        account = self._ensure_account(session, order.account_id)

        # Affordability at the real quote (entries validated with no reference).
        # A WORKING order cannot legally be rejected any more — pull it with a
        # cancel instead (rejecting here crashed the whole venue tick).
        if order.side is Side.LONG and order.filled_quantity == 0:
            cost = quote.ask * order.remaining_quantity * order.multiplier
            if cost > self._buying_power(account) and order.link.parent_order_id is None:
                order.cancel(f"insufficient buying power at execution: need ~{cost:,.0f}", ts=when)
                self._sync_row(session, row, order)
                return False

        execution = self.simulator.execute(
            side=order.side,
            quantity=order.remaining_quantity,
            quote=quote,
            instrument=order.instrument,
            limit_price=order.limit_price,
        )
        if execution.quantity <= 0:
            self._sync_row(session, row, order)
            return False

        order.record_fill(execution.quantity, execution.price, execution.fees, ts=when)
        self._sync_row(session, row, order)

        BrokerFillRepository(session).add(
            BrokerFill(
                order_id=order.order_id,
                account_id=order.account_id,
                symbol=order.symbol,
                side=order.side.value,
                quantity=execution.quantity,
                price=execution.price,
                fees=execution.fees,
                ts=when,
                partial=execution.partial,
                reason=execution.reason,
            )
        )
        self._apply_fill_to_account(
            session, account, order, execution.quantity, execution.price, execution.fees, when
        )

        if order.status is OrderStatus.FILLED:
            self._activate_children(session, order.order_id, when)
            if order.link.oco_group:
                self._cancel_oco_siblings(session, order, when)
        return True

    def _apply_fill_to_account(
        self,
        session: Session,
        account: BrokerAccount,
        order: BrokerOrder,
        quantity: int,
        price: float,
        fees: float,
        when: dt.datetime,
    ) -> None:
        """Move cash, update the position row, hold sale proceeds, journal."""
        notional = quantity * price * order.multiplier
        positions = BrokerPositionRepository(session)
        position = positions.open_position(
            account.account_id, order.symbol, instrument=order.instrument.value
        )

        if order.side is Side.LONG:
            account.cash -= notional + fees
            if position is None:
                position = BrokerPosition(
                    account_id=account.account_id,
                    symbol=order.symbol,
                    instrument=order.instrument.value,
                    side="long",
                    quantity=quantity,
                    max_quantity=quantity,
                    multiplier=order.multiplier,
                    avg_cost=price,
                    total_fees=fees,
                    last_price=price,
                    last_mark_ts=when,
                    day_start_price=price,
                    mfe_price=price,
                    mae_price=price,
                    stop_price=order.stop_price
                    if order.link.role == "entry" or order.order_type is OrderType.MARKET
                    else None,
                    opened_at=when,
                )
                positions.add(position)
            else:
                total = position.quantity + quantity
                position.avg_cost = (
                    position.avg_cost * position.quantity + price * quantity
                ) / total
                position.quantity = total
                position.max_quantity = max(position.max_quantity, total)
                position.total_fees += fees
                position.last_price = price
                position.last_mark_ts = when
        else:
            # Reduce/close a long: realize P&L, hold the proceeds for settlement.
            account.cash += notional - fees
            if position is not None:
                realized = (price - position.avg_cost) * quantity * position.multiplier - fees
                position.realized_pnl += realized
                position.quantity -= quantity
                position.total_fees += fees
                position.last_price = price
                position.last_mark_ts = when
                if position.quantity <= 0:
                    position.is_open = False
                    position.closed_at = when
            pending = _pending_from_json(account.pending_settlements)
            pending.append(
                PendingSettlement(
                    amount=notional - fees,
                    settles_at=settlement_time(when, account.settlement_days),
                )
            )
            account.pending_settlements = [p.to_dict() for p in pending]

        # Stop metadata for R-multiple math (bracket stop wins; else keep).
        if position is not None and position.stop_price and position.initial_risk_per_unit is None:
            position.initial_risk_per_unit = abs(position.avg_cost - position.stop_price)

        session.flush()
        self._append_history(
            session,
            account,
            event="fill",
            ts=when,
            detail={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": quantity,
                "price": price,
                "fees": fees,
            },
        )

    # ------------------------------------------------------------------ #
    # internals — brackets, OCO, expiry, marks
    # ------------------------------------------------------------------ #
    def _create_bracket_children(
        self, session: Session, entry: BrokerOrder, ticket: OrderTicket, *, ts: dt.datetime
    ) -> None:
        assert ticket.bracket is not None
        group = f"oco-{entry.order_id}"
        exit_side = Side.SHORT if entry.side is Side.LONG else Side.LONG

        def child(role: str, **kwargs: Any) -> None:
            child_ticket = OrderTicket(
                client_order_id=f"{entry.order_id}:{role}",
                account_id=entry.account_id,
                symbol=entry.symbol,
                side=exit_side,
                quantity=entry.quantity,
                time_in_force=TimeInForce.GTC,
                instrument=entry.instrument,
                multiplier=entry.multiplier,
                oco_group=group,
                **kwargs,
            )
            order = BrokerOrder.from_ticket(
                child_ticket,
                ts=ts,
                link=OrderLink(parent_order_id=entry.order_id, oco_group=group, role=role),
            )
            # Children rest as SUBMITTED until the entry fills.
            self._persist_new_order(session, order)

        if ticket.bracket.take_profit_limit is not None:
            child(
                "take_profit",
                order_type=OrderType.LIMIT,
                limit_price=ticket.bracket.take_profit_limit,
            )
        if ticket.bracket.stop_loss_stop is not None:
            child("stop_loss", order_type=OrderType.STOP, stop_price=ticket.bracket.stop_loss_stop)

    def _activate_children(self, session: Session, parent_id: str, when: dt.datetime) -> None:
        for row in BrokerOrderRepository(session).children_of(parent_id):
            if row.status != "submitted":
                continue
            order = self._hydrate(row)
            order.accept(ts=when)
            order.work(ts=when)
            self._sync_row(session, row, order)

    def _cancel_children(
        self, session: Session, parent_id: str, when: dt.datetime, reason: str
    ) -> None:
        for row in BrokerOrderRepository(session).children_of(parent_id):
            if OrderStatus(row.status).is_terminal:
                continue
            order = self._hydrate(row)
            order.cancel(reason, ts=when)
            self._sync_row(session, row, order)

    def _cancel_oco_siblings(
        self, session: Session, filled: BrokerOrder, when: dt.datetime
    ) -> None:
        assert filled.link.oco_group is not None
        for row in BrokerOrderRepository(session).oco_siblings(
            filled.link.oco_group, exclude=filled.order_id
        ):
            if OrderStatus(row.status).is_terminal:
                continue
            order = self._hydrate(row)
            order.cancel(f"OCO sibling {filled.order_id} filled", ts=when)
            self._sync_row(session, row, order)

    def _expire_if_due(
        self, session: Session, row: BrokerOrderRow, order: BrokerOrder, when: dt.datetime
    ) -> bool:
        if order.time_in_force is not TimeInForce.DAY or row.status == "submitted":
            return False
        if when.date() > row.created_ts.date():
            order.expire("day order not filled by the close", ts=when)
            self._sync_row(session, row, order)
            return True
        return False

    def _mark_positions(
        self, session: Session, quotes: Mapping[str, Quote], when: dt.datetime
    ) -> None:
        for account in BrokerAccountRepository(session).all_accounts():
            touched = False
            for position in BrokerPositionRepository(session).open_for_account(account.account_id):
                quote = quotes.get(position.symbol)
                if quote is None:
                    continue
                position.last_price = quote.last
                position.last_mark_ts = when
                position.mfe_price = max(position.mfe_price or quote.last, quote.last)
                position.mae_price = min(position.mae_price or quote.last, quote.last)
                if position.day_start_price is None:
                    position.day_start_price = quote.last
                touched = True
            if touched:
                self._append_history(session, account, event="mark", ts=when, detail=None)

    def _roll_day(self, session: Session, account_id: str, when: dt.datetime) -> None:
        """First interaction of a new calendar day: baseline the daily P&L."""
        account = self._ensure_account(session, account_id)
        today = when.date().isoformat()
        if account.day_start_date == today:
            return
        equity = self._equity(session, account)
        account.day_start_date = today
        account.day_start_equity = equity
        for position in BrokerPositionRepository(session).open_for_account(account_id):
            if position.last_price is not None:
                position.day_start_price = position.last_price
        self._append_history(session, account, event="day_roll", ts=when, detail=None)

    # ------------------------------------------------------------------ #
    # internals — views & math
    # ------------------------------------------------------------------ #
    def _equity(self, session: Session, account: BrokerAccount) -> float:
        value = 0.0
        for position in BrokerPositionRepository(session).open_for_account(account.account_id):
            price = position.last_price if position.last_price is not None else position.avg_cost
            value += price * position.quantity * position.multiplier
        return account.cash + value

    def _account_view(self, session: Session, account: BrokerAccount) -> AccountView:
        now = self._clock()
        pending = _pending_from_json(account.pending_settlements)
        settled, unsettled, still_pending = split_settled(account.cash, pending, now)
        if len(still_pending) != len(pending):  # some proceeds matured — persist the release
            account.pending_settlements = [p.to_dict() for p in still_pending]
            self._append_history(session, account, event="settle", ts=now, detail=None)

        positions = BrokerPositionRepository(session).open_for_account(account.account_id)
        market_value = 0.0
        cost_basis = 0.0
        open_risk = 0.0
        for position in positions:
            price = position.last_price if position.last_price is not None else position.avg_cost
            market_value += price * position.quantity * position.multiplier
            cost_basis += position.avg_cost * position.quantity * position.multiplier
            if position.stop_price is not None:
                open_risk += max(price - position.stop_price, 0.0) * (
                    position.quantity * position.multiplier
                )

        closed = [
            p
            for p in BrokerPositionRepository(session).all_for_account(account.account_id)
            if not p.is_open
        ]
        closed_pnls = [p.realized_pnl for p in closed]
        closed_rs = [
            p.realized_pnl / (p.initial_risk_per_unit * p.multiplier * max(p.max_quantity, 1))
            for p in closed
            if p.initial_risk_per_unit
        ]
        history = BrokerAccountHistoryRepository(session).equity_series(account.account_id)

        metrics = compute_account_metrics(
            settled_cash=settled,
            unsettled_cash=unsettled,
            positions_market_value=market_value,
            positions_cost_basis=cost_basis,
            open_risk=open_risk,
            starting_cash=account.starting_cash,
            margin_multiplier=account.margin_multiplier,
            day_start_equity=account.day_start_equity,
            equity_history=history,
            closed_r_multiples=closed_rs,
            closed_pnls=closed_pnls,
        )
        return AccountView(
            account_id=account.account_id,
            name=account.name,
            cash=account.cash,
            settled_cash=settled,
            unsettled_cash=unsettled,
            equity=metrics.equity,
            portfolio_value=metrics.portfolio_value,
            buying_power=metrics.buying_power,
            used_buying_power=metrics.used_buying_power,
            available_margin=metrics.available_margin,
            open_risk=metrics.open_risk,
            daily_pnl=metrics.daily_pnl,
            total_pnl=metrics.total_pnl,
            max_drawdown=metrics.max_drawdown,
            trade_count=metrics.trade_count,
            win_rate=metrics.win_rate,
            sharpe=metrics.sharpe,
            expectancy_r=metrics.expectancy_r,
            starting_cash=account.starting_cash,
            margin_multiplier=account.margin_multiplier,
            as_of=now,
        )

    def _position_view(self, position: BrokerPosition) -> PositionView:
        price = position.last_price if position.last_price is not None else position.avg_cost
        units = position.quantity * position.multiplier
        unrealized = (price - position.avg_cost) * units
        day_base = (
            position.day_start_price if position.day_start_price is not None else position.avg_cost
        )
        risk_multiple = None
        if position.initial_risk_per_unit:
            risk_multiple = (price - position.avg_cost) / position.initial_risk_per_unit
        opened = (
            position.opened_at
            if position.opened_at.tzinfo
            else position.opened_at.replace(tzinfo=dt.UTC)
        )
        return PositionView(
            account_id=position.account_id,
            symbol=position.symbol,
            instrument=InstrumentType(position.instrument),
            side=Side(position.side),
            quantity=position.quantity,
            multiplier=position.multiplier,
            avg_cost=position.avg_cost,
            last_price=position.last_price,
            market_value=price * units,
            realized_pnl=position.realized_pnl,
            unrealized_pnl=unrealized,
            todays_gain=(price - day_base) * units,
            mfe_price=position.mfe_price,
            mae_price=position.mae_price,
            risk_multiple=risk_multiple,
            stop_price=position.stop_price,
            opened_at=opened,
            days_held=max((self._clock() - opened).total_seconds() / 86_400.0, 0.0),
            is_open=position.is_open,
        )

    def _order_view(
        self, session: Session, row: BrokerOrderRow, *, with_events: bool = True
    ) -> OrderView:
        events: tuple[dict[str, Any], ...] = ()
        if with_events:
            events = tuple(
                e.to_dict() for e in BrokerOrderEventRepository(session).for_order(row.order_id)
            )
        return OrderView(
            order_id=row.order_id,
            account_id=row.account_id,
            symbol=row.symbol,
            side=Side(row.side),
            quantity=row.quantity,
            order_type=OrderType(row.order_type),
            time_in_force=TimeInForce(row.time_in_force),
            status=OrderStatus(row.status),
            limit_price=row.limit_price,
            stop_price=row.stop_price,
            trail_percent=row.trail_percent,
            trail_amount=row.trail_amount,
            filled_quantity=row.filled_quantity,
            avg_fill_price=row.avg_fill_price,
            total_fees=row.total_fees,
            reject_reason=row.reject_reason,
            parent_order_id=row.parent_order_id,
            oco_group=row.oco_group,
            link_role=row.link_role,
            instrument=InstrumentType(row.instrument),
            multiplier=row.multiplier,
            created_ts=row.created_ts,
            updated_ts=row.updated_at,
            events=events,
        )

    # ------------------------------------------------------------------ #
    # internals — persistence plumbing
    # ------------------------------------------------------------------ #
    def _persist_new_order(self, session: Session, order: BrokerOrder) -> BrokerOrderRow:
        row = BrokerOrderRow(**order.to_record())
        BrokerOrderRepository(session).add(row)
        self._persist_events(session, order)
        session.flush()
        return row

    def _sync_row(self, session: Session, row: BrokerOrderRow, order: BrokerOrder) -> None:
        record = order.to_record()
        for key, value in record.items():
            setattr(row, key, value)
        self._persist_events(session, order)
        session.flush()

    def _persist_events(self, session: Session, order: BrokerOrder) -> None:
        repo = BrokerOrderEventRepository(session)
        for event in order.events[order.events_persisted :]:
            repo.add(
                BrokerOrderEvent(
                    order_id=order.order_id,
                    ts=event.ts,
                    from_status=event.from_status.value,
                    to_status=event.to_status.value,
                    reason=event.reason,
                    payload=event.payload,
                )
            )
        order.events_persisted = len(order.events)

    def _hydrate(self, row: BrokerOrderRow) -> BrokerOrder:
        """Rebuild the in-memory state machine from the persisted row + events."""
        order = BrokerOrder(
            order_id=row.order_id,
            account_id=row.account_id,
            symbol=row.symbol,
            side=Side(row.side),
            quantity=row.quantity,
            order_type=OrderType(row.order_type),
            time_in_force=TimeInForce(row.time_in_force),
            created_ts=row.created_ts,
            limit_price=row.limit_price,
            stop_price=row.stop_price,
            trail_percent=row.trail_percent,
            trail_amount=row.trail_amount,
            instrument=InstrumentType(row.instrument),
            multiplier=row.multiplier,
            link=OrderLink(
                parent_order_id=row.parent_order_id,
                oco_group=row.oco_group,
                role=row.link_role,
            ),
            note=row.note,
            status=OrderStatus(row.status),
            filled_quantity=row.filled_quantity,
            fill_notional=(row.avg_fill_price or 0.0) * row.filled_quantity * row.multiplier,
            total_fees=row.total_fees,
            reject_reason=row.reject_reason,
            trail_extreme=row.trail_extreme,
        )
        # A hydrated order starts with an empty in-memory event list; the
        # stored events stay in the DB and only NEW transitions get appended
        # (events_persisted == 0 == len(events), so nothing is re-written).
        return order

    def _require_order(self, session: Session, order_id: str) -> BrokerOrderRow:
        row = BrokerOrderRepository(session).by_order_id(order_id)
        if row is None:
            raise InvalidOrderStateError(f"unknown order: {order_id}")
        return row

    def _append_history(
        self,
        session: Session,
        account: BrokerAccount,
        *,
        event: str,
        ts: dt.datetime,
        detail: dict[str, Any] | None,
    ) -> None:
        pending = _pending_from_json(account.pending_settlements)
        settled, unsettled, _ = split_settled(account.cash, pending, ts)
        equity = self._equity(session, account)
        positions_value = equity - account.cash
        day_start = account.day_start_equity if account.day_start_equity is not None else equity
        BrokerAccountHistoryRepository(session).add(
            BrokerAccountHistory(
                account_id=account.account_id,
                ts=ts,
                event=event,
                cash=account.cash,
                settled_cash=settled,
                unsettled_cash=unsettled,
                equity=equity,
                portfolio_value=positions_value,
                buying_power=max(settled, 0.0) * account.margin_multiplier,
                open_risk=0.0,
                daily_pnl=equity - day_start,
                total_pnl=equity - account.starting_cash,
                detail=detail,
            )
        )


def _pending_from_json(raw: list[dict[str, Any]] | None) -> list[PendingSettlement]:
    out: list[PendingSettlement] = []
    for item in raw or []:
        try:
            out.append(
                PendingSettlement(
                    amount=float(item["amount"]),
                    settles_at=dt.datetime.fromisoformat(str(item["settles_at"])),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out
