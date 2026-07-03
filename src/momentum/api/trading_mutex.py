"""One trading pipeline at a time — the process-wide trading mutex.

The daemon's scan cycle, the manual "Run Scan" job, the manual
reevaluate-trades job and the synchronous Take/Track/Close trade actions
all mutate the same surfaces (scan rows, tracked trades, the paper
journal, the brokerage venue). Two of them running concurrently is how
money gets double-managed: both see a scale-out target as un-hit and both
reduce, or both see a symbol as un-held and both enter.

:func:`exclusive` grants at most ONE holder per process. It is
**re-entrant on the same thread** (autopilot's take runs inside the scan
that holds the mutex) but a second *thread* is refused immediately with
:class:`TradingPipelineBusyError` — never queued. The daemon simply
records the failed cycle and retries next tick; a manual action returns
an honest "a scan is running" error instead of silently interleaving.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

_LOCK = threading.RLock()
# The outermost holder's label, for the refusal message. Only ever written
# while the lock is held, so reads can at worst see a fresh/stale label.
_holder: str | None = None


class TradingPipelineBusyError(RuntimeError):
    """Another trading pipeline holds the mutex on a different thread."""


@contextmanager
def exclusive(label: str) -> Iterator[None]:
    """Hold the trading mutex for the duration (refuse, don't queue)."""
    global _holder
    if not _LOCK.acquire(blocking=False):
        raise TradingPipelineBusyError(
            f"'{label}' refused: '{_holder or 'another trading pipeline'}' is already "
            "running — concurrent trading pipelines are serialized for safety; retry "
            "when it completes"
        )
    outermost = _holder is None
    if outermost:
        _holder = label
    try:
        yield
    finally:
        if outermost:
            _holder = None
        _LOCK.release()


def serialized(label: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator form of :func:`exclusive` for the pipeline entry points."""

    def decorate(fn: Callable[P, T]) -> Callable[P, T]:
        @wraps(fn)
        def inner(*args: P.args, **kwargs: P.kwargs) -> T:
            with exclusive(label):
                return fn(*args, **kwargs)

        return inner

    return decorate


def holder() -> str | None:
    """The label of the pipeline currently holding the mutex (diagnostics)."""
    return _holder
