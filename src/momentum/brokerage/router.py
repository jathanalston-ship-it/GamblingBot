"""The OrderRouter — the single door every trading instruction walks through.

The decision engine emits intent (an :class:`OrderTicket`); the router
picks the configured adapter, checks the ticket against the venue's
declared :class:`BrokerCapabilities` (an unsupported order is refused with
a named reason before the venue ever sees it), delegates, and returns a
normalized :class:`ExecutionReport`. Every routing decision — accepted or
refused — lands in a bounded in-memory log for diagnostics.

The router is how paper/simulation/live stay interchangeable: registering
a live adapter changes routing configuration, not decision code.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections import deque
from typing import Any

from momentum.brokerage.adapter import BrokerAdapter
from momentum.brokerage.reports import ExecutionReport
from momentum.brokerage.types import ModifyTicket, OrderTicket

_log = logging.getLogger(__name__)


class OrderRouter:
    """Routes tickets to the configured broker adapter."""

    def __init__(self, *, default: str | None = None, log_size: int = 200) -> None:
        self._adapters: dict[str, BrokerAdapter] = {}
        self._default = default
        self._log: deque[dict[str, Any]] = deque(maxlen=log_size)
        self._lock = threading.Lock()

    def register(self, adapter: BrokerAdapter, *, default: bool = False) -> None:
        with self._lock:
            self._adapters[adapter.name] = adapter
            if default or self._default is None:
                self._default = adapter.name

    def adapter(self, broker: str | None = None) -> BrokerAdapter:
        with self._lock:
            key = broker or self._default
            if key is None or key not in self._adapters:
                raise KeyError(f"no broker adapter registered for {key!r}")
            return self._adapters[key]

    @property
    def brokers(self) -> list[str]:
        with self._lock:
            return sorted(self._adapters)

    @property
    def default_broker(self) -> str | None:
        return self._default

    # ------------------------------------------------------------------ #
    # trading
    # ------------------------------------------------------------------ #
    def submit(
        self, ticket: OrderTicket, *, broker: str | None = None, ts: dt.datetime | None = None
    ) -> ExecutionReport:
        adapter = self.adapter(broker)
        when = ts or dt.datetime.now(tz=dt.UTC)
        reason = adapter.capabilities.rejection_reason(ticket)
        if reason is not None:
            report = ExecutionReport(
                action="place",
                broker=adapter.name,
                mode=adapter.capabilities.mode,
                accepted=False,
                reason=reason,
                order=None,
                ts=when,
            )
            self._record(report, symbol=ticket.symbol)
            return report
        view = adapter.place_order(ticket, ts=ts)
        report = ExecutionReport(
            action="place",
            broker=adapter.name,
            mode=adapter.capabilities.mode,
            accepted=view.status.value != "rejected",
            reason=view.reject_reason,
            order=view,
            ts=when,
        )
        self._record(report, symbol=ticket.symbol)
        return report

    def cancel(
        self, order_id: str, *, broker: str | None = None, ts: dt.datetime | None = None
    ) -> ExecutionReport:
        adapter = self.adapter(broker)
        view = adapter.cancel_order(order_id, ts=ts)
        report = ExecutionReport(
            action="cancel",
            broker=adapter.name,
            mode=adapter.capabilities.mode,
            accepted=True,
            reason=None,
            order=view,
            ts=ts or dt.datetime.now(tz=dt.UTC),
        )
        self._record(report, symbol=view.symbol)
        return report

    def modify(
        self, ticket: ModifyTicket, *, broker: str | None = None, ts: dt.datetime | None = None
    ) -> ExecutionReport:
        adapter = self.adapter(broker)
        view = adapter.modify_order(ticket, ts=ts)
        report = ExecutionReport(
            action="modify",
            broker=adapter.name,
            mode=adapter.capabilities.mode,
            accepted=True,
            reason=None,
            order=view,
            ts=ts or dt.datetime.now(tz=dt.UTC),
        )
        self._record(report, symbol=view.symbol)
        return report

    def close(
        self,
        account_id: str,
        symbol: str,
        *,
        quantity: int | None = None,
        broker: str | None = None,
        ts: dt.datetime | None = None,
    ) -> ExecutionReport:
        adapter = self.adapter(broker)
        view = adapter.close_position(account_id, symbol, quantity=quantity, ts=ts)
        report = ExecutionReport(
            action="close",
            broker=adapter.name,
            mode=adapter.capabilities.mode,
            accepted=view.status.value != "rejected",
            reason=view.reject_reason,
            order=view,
            ts=ts or dt.datetime.now(tz=dt.UTC),
        )
        self._record(report, symbol=symbol.upper())
        return report

    # ------------------------------------------------------------------ #
    # diagnostics
    # ------------------------------------------------------------------ #
    def routing_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log)[:limit]

    def _record(self, report: ExecutionReport, *, symbol: str) -> None:
        entry = {
            "ts": report.ts.isoformat(),
            "action": report.action,
            "broker": report.broker,
            "mode": report.mode,
            "symbol": symbol,
            "accepted": report.accepted,
            "reason": report.reason,
            "order_id": report.order_id,
            "status": report.status,
        }
        with self._lock:
            self._log.appendleft(entry)
        if not report.accepted:
            _log.warning("order refused by router/venue: %s", entry)
