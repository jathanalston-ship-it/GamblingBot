"""Trading-mutex semantics: one pipeline at a time, refuse-don't-queue."""

from __future__ import annotations

import threading

import pytest

from momentum.api import trading_mutex
from momentum.api.trading_mutex import TradingPipelineBusyError, exclusive, serialized


def test_grants_and_releases() -> None:
    with exclusive("scan"):
        assert trading_mutex.holder() == "scan"
    assert trading_mutex.holder() is None


def test_reentrant_on_the_same_thread() -> None:
    """Autopilot's take runs inside the scan holding the mutex — no deadlock."""
    with exclusive("scan"), exclusive("take-trade"):
        assert trading_mutex.holder() == "scan"  # the outermost label wins
    assert trading_mutex.holder() is None


def test_second_thread_is_refused_immediately() -> None:
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with exclusive("scan"):
            held.set()
            release.wait(timeout=5.0)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert held.wait(timeout=5.0)
    with pytest.raises(TradingPipelineBusyError, match="'scan' is already running"):
        with exclusive("take-trade"):
            pytest.fail("must never be granted while another thread holds the mutex")
    release.set()
    thread.join(timeout=5.0)
    with exclusive("take-trade"):  # released cleanly — grantable again
        assert trading_mutex.holder() == "take-trade"


def test_released_on_exception() -> None:
    with pytest.raises(ValueError, match="boom"):
        with exclusive("scan"):
            raise ValueError("boom")
    assert trading_mutex.holder() is None
    with exclusive("scan"):
        pass


def test_serialized_decorator() -> None:
    @serialized("scan")
    def pipeline(x: int) -> int:
        assert trading_mutex.holder() == "scan"
        return x * 2

    assert pipeline(21) == 42
    assert trading_mutex.holder() is None
