"""Operator overrides for ad-hoc NYSE schedule changes (immutable Pydantic).

No algorithm can predict an *unscheduled* market closure or early close — a
national day of mourning, a weather closure, a one-off half day. This config is
how an operator declares one the moment the exchange announces it: add the date
to ``config/market_calendar.yaml`` (a writable per-user override of the shipped
example) and it takes effect on the next restart across scheduling, the live
clock and any calendar-driven logic — no code change, no release.

Known *historical* ad-hoc closures are already baked into
:mod:`momentum.data.calendar` as facts; this config is only for future,
un-derivable dates.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from momentum.core.config_paths import load_config
from momentum.data.calendar import TradingCalendar

_EXAMPLE = "market_calendar.example.yaml"
_EMBEDDED: dict[str, Any] = {"model_version": "v1", "closures": [], "early_closes": []}


class MarketCalendarConfig(BaseModel):
    """Operator-declared full-day closures and one-off early closes (ET dates)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    closures: tuple[dt.date, ...] = ()  # unscheduled full-day closures
    early_closes: tuple[dt.date, ...] = ()  # unscheduled 13:00-ET early closes

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketCalendarConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> MarketCalendarConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_market_calendar_config() -> MarketCalendarConfig:
    """Resolve overrides: user file → shipped example → embedded empty default."""
    return MarketCalendarConfig.from_dict(load_config(_EXAMPLE, embedded=_EMBEDDED))


def build_calendar(config: MarketCalendarConfig | None = None) -> TradingCalendar:
    """A ``TradingCalendar`` with the operator overrides merged in (curated
    historical closures are always present regardless of config)."""
    cfg = config or load_market_calendar_config()
    return TradingCalendar(
        extra_closures=frozenset(cfg.closures),
        extra_early_closes=frozenset(cfg.early_closes),
    )
