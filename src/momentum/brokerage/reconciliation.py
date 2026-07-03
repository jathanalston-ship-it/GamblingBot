"""Broker reconciliation — the venue's word is verified, never assumed.

On a cadence (default every 30 seconds while the loop runs, plus after
every venue tick) the reconciler compares **broker state** — positions,
cash, orders, fills, buying power, read through the Brokerage protocol —
against the **local database's immutable fills trail**, which is the
system of record:

* **missing fills** — an order claims more filled quantity than its fills;
* **duplicate fills** — the same execution recorded twice;
* **incorrect quantities / average price** — a position row disagreeing
  with what its fills imply;
* **cancelled orders** — terminal-cancelled orders holding excess fills;
* **unexpected executions** — a fill whose order the local DB never saw.

Resolution policy — **automatically reconcile, never silently overwrite**:

* *Derived* state (position rows) is corrected to match the immutable
  fills trail, and every correction is recorded in the discrepancy report
  **and** the append-only audit log.
* *Money and the trail itself* (cash, fills, orders) are never rewritten —
  a mismatch there is flagged ``critical`` for the operator with the exact
  local-vs-broker values.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from momentum.brokerage.interface import Brokerage
from momentum.core.enums import AuditEvent
from momentum.persistence.audit import AuditRecord
from momentum.persistence.models.broker import BrokerFill, BrokerOrderRow, BrokerPosition
from momentum.persistence.repositories.audit_log import AuditLogRepository

_log = logging.getLogger(__name__)

PRICE_TOLERANCE = 0.01  # dollars on avg cost
CASH_TOLERANCE = 0.01  # dollars on cash / buying power


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One local-vs-broker disagreement, with what was done about it."""

    kind: str  # missing_fill | duplicate_fill | incorrect_quantity |
    #            incorrect_avg_price | cancelled_order_excess_fills |
    #            unexpected_execution | cash_mismatch | buying_power_mismatch
    severity: str  # warning | critical
    symbol: str | None
    order_id: str | None
    local: str
    broker: str
    detail: str
    resolution: str  # flagged | auto_corrected

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "symbol": self.symbol,
            "order_id": self.order_id,
            "local": self.local,
            "broker": self.broker,
            "detail": self.detail,
            "resolution": self.resolution,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """One reconciliation pass: what was compared, what disagreed."""

    account_id: str
    ts: dt.datetime
    checks_run: tuple[str, ...]
    fills_seen: int
    orders_seen: int
    positions_seen: int
    discrepancies: tuple[Discrepancy, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        return not self.discrepancies

    @property
    def corrections(self) -> int:
        return sum(1 for d in self.discrepancies if d.resolution == "auto_corrected")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "ts": self.ts.isoformat(),
            "clean": self.clean,
            "checks_run": list(self.checks_run),
            "fills_seen": self.fills_seen,
            "orders_seen": self.orders_seen,
            "positions_seen": self.positions_seen,
            "corrections": self.corrections,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
        }


@dataclass(slots=True)
class _Expected:
    quantity: int = 0
    avg_cost: float = 0.0
    cash_delta: float = 0.0


def replay_fills(
    fills: list[BrokerFill], multipliers: dict[str, int]
) -> tuple[dict[str, _Expected], float]:
    """Rebuild expected per-symbol position + total cash delta from the trail.

    Pure long-only accounting, mirroring the venue's fill application. The
    fills trail is append-only, so this is the ground truth.
    """
    expected: dict[str, _Expected] = {}
    cash = 0.0
    for fill in sorted(fills, key=lambda f: (f.ts, f.id)):
        state = expected.setdefault(fill.symbol, _Expected())
        multiplier = multipliers.get(fill.order_id, 1)
        notional = fill.quantity * fill.price * multiplier
        if fill.side == "long":
            total = state.quantity + fill.quantity
            state.avg_cost = (
                (state.avg_cost * state.quantity + fill.price * fill.quantity) / total
                if total
                else 0.0
            )
            state.quantity = total
            cash -= notional + fill.fees
        else:
            state.quantity -= fill.quantity
            cash += notional - fill.fees
    return expected, cash


class Reconciler:
    """Compares broker state against the local fills trail and resolves."""

    def __init__(self, session_factory: sessionmaker[Session], brokerage: Brokerage) -> None:
        self._session_factory = session_factory
        self._brokerage = brokerage

    def reconcile(
        self,
        account_id: str = "primary",
        *,
        apply_corrections: bool = True,
        ts: dt.datetime | None = None,
    ) -> ReconciliationReport:
        when = ts or dt.datetime.now(tz=dt.UTC)
        found: list[Discrepancy] = []

        with self._session_factory() as session:
            fills = list(session.query(BrokerFill).filter_by(account_id=account_id).all())
            orders = {
                row.order_id: row
                for row in session.query(BrokerOrderRow).filter_by(account_id=account_id).all()
            }
            found.extend(self._check_fill_trail(fills, orders))
            expected, cash_delta = replay_fills(
                fills, {oid: row.multiplier for oid, row in orders.items()}
            )
            found.extend(
                self._check_positions(session, account_id, expected, apply_corrections, when)
            )
            if apply_corrections and any(d.resolution == "auto_corrected" for d in found):
                session.commit()
            else:
                session.rollback()

        found.extend(self._check_account(account_id, cash_delta))

        report = ReconciliationReport(
            account_id=account_id,
            ts=when,
            checks_run=(
                "fills_vs_orders",
                "duplicate_fills",
                "positions_vs_fills",
                "cash_vs_fills",
                "buying_power",
            ),
            fills_seen=len(fills),
            orders_seen=len(orders),
            positions_seen=len(expected),
            discrepancies=tuple(found),
        )
        if not report.clean:
            self._persist_report(report)
        return report

    # ------------------------------------------------------------------ #
    # checks
    # ------------------------------------------------------------------ #
    def _check_fill_trail(
        self, fills: list[BrokerFill], orders: dict[str, BrokerOrderRow]
    ) -> list[Discrepancy]:
        found: list[Discrepancy] = []

        counted = Counter((f.order_id, f.ts, f.quantity, round(f.price, 6)) for f in fills)
        for (order_id, fill_ts, quantity, price), n in counted.items():
            if n > 1:
                found.append(
                    Discrepancy(
                        kind="duplicate_fill",
                        severity="critical",
                        symbol=None,
                        order_id=order_id,
                        local=f"{n} identical fills",
                        broker="1 execution expected",
                        detail=(
                            f"fill ({quantity} @ {price} at {fill_ts}) recorded {n} times — "
                            "an execution must land exactly once"
                        ),
                        resolution="flagged",
                    )
                )

        by_order: dict[str, int] = {}
        for fill in fills:
            by_order[fill.order_id] = by_order.get(fill.order_id, 0) + fill.quantity
            if fill.order_id not in orders:
                found.append(
                    Discrepancy(
                        kind="unexpected_execution",
                        severity="critical",
                        symbol=fill.symbol,
                        order_id=fill.order_id,
                        local="no such order",
                        broker=f"fill {fill.quantity} @ {fill.price}",
                        detail="a fill arrived for an order the local database never saw",
                        resolution="flagged",
                    )
                )

        for order_id, row in orders.items():
            filled = by_order.get(order_id, 0)
            if row.filled_quantity > filled:
                found.append(
                    Discrepancy(
                        kind="missing_fill",
                        severity="critical",
                        symbol=row.symbol,
                        order_id=order_id,
                        local=f"{filled} shares of fills",
                        broker=f"order reports {row.filled_quantity} filled",
                        detail="the order claims more filled quantity than its fills account for",
                        resolution="flagged",
                    )
                )
            elif row.filled_quantity < filled:
                kind = (
                    "cancelled_order_excess_fills"
                    if row.status == "cancelled"
                    else "unexpected_execution"
                )
                found.append(
                    Discrepancy(
                        kind=kind,
                        severity="critical",
                        symbol=row.symbol,
                        order_id=order_id,
                        local=f"order reports {row.filled_quantity} filled ({row.status})",
                        broker=f"{filled} shares of fills exist",
                        detail="more fills exist than the order ever acknowledged",
                        resolution="flagged",
                    )
                )
        return found

    def _check_positions(
        self,
        session: Session,
        account_id: str,
        expected: dict[str, _Expected],
        apply_corrections: bool,
        when: dt.datetime,
    ) -> list[Discrepancy]:
        found: list[Discrepancy] = []
        rows: dict[str, BrokerPosition] = {}
        for p in session.query(BrokerPosition).filter_by(account_id=account_id).all():
            existing = rows.get(p.symbol)
            if existing is None or (p.is_open and not existing.is_open):
                rows[p.symbol] = p  # the open row wins for re-opened symbols
        for symbol, exp in expected.items():
            row = rows.get(symbol)
            broker_qty = row.quantity if row is not None and row.is_open else 0
            if broker_qty != max(exp.quantity, 0):
                resolution = "flagged"
                if apply_corrections and row is not None:
                    row.quantity = max(exp.quantity, 0)
                    row.is_open = exp.quantity > 0
                    resolution = "auto_corrected"
                found.append(
                    Discrepancy(
                        kind="incorrect_quantity",
                        severity="critical",
                        symbol=symbol,
                        order_id=None,
                        local=f"fills imply {max(exp.quantity, 0)}",
                        broker=f"position row shows {broker_qty}",
                        detail="position corrected to the immutable fills trail"
                        if resolution == "auto_corrected"
                        else "no position row exists to correct — flagged",
                        resolution=resolution,
                    )
                )
                continue
            if (
                row is not None
                and row.is_open
                and exp.quantity > 0
                and abs(row.avg_cost - exp.avg_cost) > PRICE_TOLERANCE
            ):
                resolution = "flagged"
                if apply_corrections:
                    row.avg_cost = exp.avg_cost
                    resolution = "auto_corrected"
                found.append(
                    Discrepancy(
                        kind="incorrect_avg_price",
                        severity="warning",
                        symbol=symbol,
                        order_id=None,
                        local=f"fills imply avg cost {exp.avg_cost:.4f}",
                        broker=f"position row shows {row.avg_cost:.4f}",
                        detail="average cost corrected to the immutable fills trail"
                        if resolution == "auto_corrected"
                        else "flagged for operator review",
                        resolution=resolution,
                    )
                )
        return found

    def _check_account(self, account_id: str, cash_delta: float) -> list[Discrepancy]:
        found: list[Discrepancy] = []
        account = self._brokerage.get_account(account_id)
        expected_cash = account.starting_cash + cash_delta
        if abs(account.cash - expected_cash) > CASH_TOLERANCE:
            found.append(
                Discrepancy(
                    kind="cash_mismatch",
                    severity="critical",
                    symbol=None,
                    order_id=None,
                    local=f"fills imply cash {expected_cash:,.2f}",
                    broker=f"account reports {account.cash:,.2f}",
                    detail="cash is NEVER auto-corrected — money mismatches are "
                    "flagged for the operator with both values",
                    resolution="flagged",
                )
            )
        expected_bp = max(account.settled_cash, 0.0) * account.margin_multiplier
        if abs(account.buying_power - expected_bp) > CASH_TOLERANCE:
            found.append(
                Discrepancy(
                    kind="buying_power_mismatch",
                    severity="critical",
                    symbol=None,
                    order_id=None,
                    local=f"settled x margin implies {expected_bp:,.2f}",
                    broker=f"account reports {account.buying_power:,.2f}",
                    detail="buying power must equal settled cash x margin",
                    resolution="flagged",
                )
            )
        return found

    # ------------------------------------------------------------------ #
    # persistence — discrepancy reports are part of the audit trail
    # ------------------------------------------------------------------ #
    def _persist_report(self, report: ReconciliationReport) -> None:
        try:
            with self._session_factory() as session:
                AuditLogRepository(session).append(
                    AuditRecord(
                        event=AuditEvent.RECONCILIATION,
                        summary=(
                            f"reconciliation found {len(report.discrepancies)} discrepancies "
                            f"({report.corrections} auto-corrected) on {report.account_id}"
                        ),
                        ts=report.ts,
                        entity_type="account",
                        entity_id=report.account_id,
                        payload=report.to_dict(),
                    ).to_model()
                )
                session.commit()
        except Exception:  # noqa: BLE001 — reporting must never break trading
            _log.warning("failed to persist reconciliation report", exc_info=True)


class ReconciliationLoop:
    """Runs the reconciler on a cadence (default: every 30 seconds).

    A dedicated daemon thread; ``stop()`` joins it. The freshest report is
    kept on the loop for the API to serve. A failing pass is logged and the
    loop keeps going — reconciliation must outlive transient errors.
    """

    def __init__(self, reconciler: Reconciler, *, interval_seconds: float = 30.0) -> None:
        self._reconciler = reconciler
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_report: ReconciliationReport | None = None
        self.passes = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mrp-reconciler", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stop.is_set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.last_report = self._reconciler.reconcile()
                self.passes += 1
            except Exception:  # noqa: BLE001 — the loop must never die
                _log.warning("reconciliation pass failed", exc_info=True)
            self._stop.wait(timeout=self.interval_seconds)
