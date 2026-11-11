"""Suite-wide fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _every_bar_is_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the strategy's live clock so no test depends on the time of day.

    Live scans drop a still-forming daily bar (dated today, before the close)
    from every signal. Many tests build bars that end *today*; with the real
    clock their signals would differ between a morning and an evening run.
    ``None`` treats every bar as complete. Tests of the dropping behaviour pass
    an explicit ``now`` (or re-patch this) themselves.
    """
    monkeypatch.setattr("momentum.strategy.rules.live_clock", lambda: None)
