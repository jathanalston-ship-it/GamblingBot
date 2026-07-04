"""Tests for the operator-override market-calendar config + builder."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

from momentum.data.calendar_config import (
    MarketCalendarConfig,
    build_calendar,
    load_market_calendar_config,
)


def test_defaults_are_empty() -> None:
    cfg = MarketCalendarConfig()
    assert cfg.closures == () and cfg.early_closes == ()


def test_from_dict_parses_dates() -> None:
    cfg = MarketCalendarConfig.from_dict(
        {"closures": ["2027-03-15"], "early_closes": ["2027-07-06"]}
    )
    assert cfg.closures == (dt.date(2027, 3, 15),)
    assert cfg.early_closes == (dt.date(2027, 7, 6),)


def test_extra_key_rejected() -> None:
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError (extra=forbid)
        MarketCalendarConfig.from_dict({"nope": 1})


def test_config_hash_is_stable_and_sensitive() -> None:
    a = MarketCalendarConfig.from_dict({"closures": ["2027-03-15"]})
    b = MarketCalendarConfig.from_dict({"closures": ["2027-03-15"]})
    c = MarketCalendarConfig.from_dict({"closures": ["2027-03-16"]})
    assert a.config_hash() == b.config_hash() != c.config_hash()


def test_build_calendar_applies_overrides() -> None:
    cfg = MarketCalendarConfig.from_dict(
        {"closures": ["2027-03-15"], "early_closes": ["2027-07-06"]}
    )
    cal = build_calendar(cfg)
    assert not cal.is_session(dt.date(2027, 3, 15))  # declared full closure
    assert cal.is_half_day(dt.date(2027, 7, 6))  # declared early close


def test_declared_closure_beats_declared_early_close() -> None:
    cfg = MarketCalendarConfig.from_dict(
        {"closures": ["2027-07-06"], "early_closes": ["2027-07-06"]}
    )
    cal = build_calendar(cfg)
    assert not cal.is_session(dt.date(2027, 7, 6))
    assert not cal.is_half_day(dt.date(2027, 7, 6))  # a full closure wins


def test_from_yaml_and_shipped_example_loads(tmp_path: Path) -> None:
    path = tmp_path / "market_calendar.yaml"
    path.write_text(yaml.safe_dump({"closures": ["2028-01-03"]}))
    cfg = MarketCalendarConfig.from_yaml(path)
    assert cfg.closures == (dt.date(2028, 1, 3),)


def test_load_market_calendar_config_uses_user_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "market_calendar.yaml").write_text(yaml.safe_dump({"closures": ["2029-05-01"]}))
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    cfg = load_market_calendar_config()
    assert dt.date(2029, 5, 1) in cfg.closures
