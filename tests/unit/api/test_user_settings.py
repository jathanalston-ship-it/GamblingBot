"""Tests for the writable user-settings store (provider choice + API keys)."""

from __future__ import annotations

import pytest

from momentum.api import user_settings


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    """Point the settings store at a temp dir and clear provider env vars."""
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    for var in user_settings.PROVIDER_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_defaults_when_nothing_written(user_dir):
    s = user_settings.read_provider_settings()
    assert s.provider == user_settings.DEFAULT_PROVIDER == "yfinance"
    assert s.keys_present == {k: False for k in user_settings.PROVIDER_KEYS}
    assert "alpaca" in s.valid_providers and "polygon" in s.valid_providers


def test_write_provider_persists_to_settings_yaml(user_dir):
    user_settings.write_provider_settings("alpaca", {})
    assert (user_dir / "settings.yaml").is_file()
    # A fresh read reflects the choice.
    assert user_settings.read_provider() == "alpaca"


def test_write_secrets_to_env_and_reported_present(user_dir):
    s = user_settings.write_provider_settings(
        "alpaca",
        {"alpaca_api_key": "KEY123", "alpaca_api_secret": "SECRET456"},
    )
    assert s.keys_present["alpaca_api_key"] is True
    assert s.keys_present["alpaca_api_secret"] is True
    assert s.keys_present["polygon_api_key"] is False
    # Stored in .env and pushed into the live process env.
    env_text = (user_dir / ".env").read_text()
    assert "ALPACA_API_KEY=KEY123" in env_text
    assert "ALPACA_API_SECRET=SECRET456" in env_text


def test_secret_values_never_returned(user_dir):
    s = user_settings.write_provider_settings("polygon", {"polygon_api_key": "TOPSECRET"})
    # The settings object exposes only booleans, not the secret value.
    assert "TOPSECRET" not in repr(s)
    assert s.keys_present["polygon_api_key"] is True


def test_blank_key_leaves_existing_untouched(user_dir):
    user_settings.write_provider_settings("alpaca", {"alpaca_api_key": "ORIGINAL"})
    # Re-save with a blank key (e.g. user didn't retype it) -> kept.
    user_settings.write_provider_settings("alpaca", {"alpaca_api_key": ""})
    assert "ALPACA_API_KEY=ORIGINAL" in (user_dir / ".env").read_text()
    assert user_settings.read_provider_settings().keys_present["alpaca_api_key"] is True


def test_env_merge_preserves_unrelated_keys(user_dir):
    (user_dir / ".env").write_text("UNRELATED=keepme\nALPACA_API_KEY=old\n")
    user_settings.write_provider_settings("alpaca", {"alpaca_api_key": "new"})
    text = (user_dir / ".env").read_text()
    assert "UNRELATED=keepme" in text
    assert "ALPACA_API_KEY=new" in text


def test_settings_yaml_merge_preserves_other_keys(user_dir):
    (user_dir / "settings.yaml").write_text("environment: research\ndata:\n  timeframe: 1d\n")
    user_settings.write_provider_settings("polygon", {})
    parsed = user_settings._read_settings_yaml()
    assert parsed["environment"] == "research"
    assert parsed["data"]["timeframe"] == "1d"  # type: ignore[index]
    assert parsed["data"]["provider"] == "polygon"  # type: ignore[index]


def test_unknown_provider_rejected(user_dir):
    with pytest.raises(user_settings.UnknownProviderError):
        user_settings.write_provider_settings("nasdaq-direct", {})


def test_load_user_env_populates_process_env(user_dir, monkeypatch):
    (user_dir / ".env").write_text("POLYGON_API_KEY=fromfile\n")
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    user_settings.load_user_env()
    import os

    assert os.environ["POLYGON_API_KEY"] == "fromfile"


def test_build_provider_matches_selection(user_dir, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    user_settings.write_provider_settings("alpaca", {})
    assert user_settings.build_provider().name == "alpaca"

    user_settings.write_provider_settings("yfinance", {})
    assert user_settings.build_provider().name == "yahoo"
