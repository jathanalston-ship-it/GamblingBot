"""Writable user settings: the data-provider choice + API-key secrets.

The shipped ``config/*.example.yaml`` templates are read-only references. The
*user-editable* settings live in a per-user **writable** directory (``MRP_USER_DIR``;
the desktop app points this at ``%APPDATA%/Momentum Lab``). Two stores:

* ``settings.yaml`` — the non-secret data-provider choice (and any other tunables).
* ``.env`` — secrets (provider API keys). These are **never** returned in plain
  text by the API; callers only learn whether a key *is set* (a boolean).

Writes take effect immediately (the new secrets are pushed into ``os.environ`` so
the next provider build authenticates) and persist across restarts
(:func:`load_user_env` re-loads ``.env`` at startup).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from momentum.data.providers.base import MarketDataProvider

# Provider keys accepted by settings.yaml's ``data.provider`` (UI value -> impl).
VALID_PROVIDERS: tuple[str, ...] = ("yfinance", "alpaca", "polygon")
DEFAULT_PROVIDER = "yfinance"

# UI field name -> environment variable holding the secret. The env var names
# match what the provider adapters read (see data/providers/{alpaca,polygon}.py).
PROVIDER_KEYS: dict[str, str] = {
    "alpaca_api_key": "ALPACA_API_KEY",
    "alpaca_api_secret": "ALPACA_API_SECRET",
    "polygon_api_key": "POLYGON_API_KEY",
}


class UnknownProviderError(ValueError):
    """Raised when an unsupported provider name is written."""


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Current data-provider selection and which secret keys are present."""

    provider: str
    keys_present: dict[str, bool]
    valid_providers: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Paths (a single writable user directory, overridable for tests/desktop).
# --------------------------------------------------------------------------- #
def _user_dir() -> Path:
    override = os.environ.get("MRP_USER_DIR")
    if override:
        return Path(override).resolve()
    return Path.cwd().resolve()  # dev fallback: the repo root


def _settings_path() -> Path:
    return _user_dir() / "settings.yaml"


def _env_path() -> Path:
    return _user_dir() / ".env"


# --------------------------------------------------------------------------- #
# .env (KEY=value) — a minimal, dependency-free reader/writer that preserves
# any unrelated keys already in the file.
# --------------------------------------------------------------------------- #
def _read_env_file() -> dict[str, str]:
    path = _env_path()
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def _write_env_file(values: dict[str, str]) -> None:
    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(values.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


# --------------------------------------------------------------------------- #
# settings.yaml — read/merge the data-provider choice, preserving other keys.
# --------------------------------------------------------------------------- #
def _read_settings_yaml() -> dict[str, object]:
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def read_provider() -> str:
    """The configured provider, or the default if unset/invalid."""
    section = _read_settings_yaml().get("data")
    if isinstance(section, dict):
        provider = section.get("provider")
        if isinstance(provider, str) and provider in VALID_PROVIDERS:
            return provider
    return DEFAULT_PROVIDER


def read_selected_universe() -> str:
    """The selected scanner-universe key (``"default"`` if unset)."""
    from momentum.universe.universes import DEFAULT_UNIVERSE_KEY

    section = _read_settings_yaml().get("universe")
    if isinstance(section, dict):
        selected = section.get("selected")
        if isinstance(selected, str) and selected:
            return selected
    return DEFAULT_UNIVERSE_KEY


def write_selected_universe(key: str) -> str:
    """Persist the selected scanner-universe key to ``settings.yaml``."""
    data = _read_settings_yaml()
    section = data.get("universe")
    if not isinstance(section, dict):
        section = {}
    section["selected"] = key
    data["universe"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return key


# Data mode: "demo" (sample data allowed) vs "production" (live data only).
VALID_DATA_MODES: tuple[str, ...] = ("demo", "production")
DEFAULT_DATA_MODE = "demo"


def read_data_mode() -> str:
    """The configured data mode (``"demo"`` if unset/invalid)."""
    section = _read_settings_yaml().get("data")
    if isinstance(section, dict):
        mode = section.get("mode")
        if isinstance(mode, str) and mode in VALID_DATA_MODES:
            return mode
    return DEFAULT_DATA_MODE


def write_data_mode(mode: str) -> str:
    """Persist the data mode to ``settings.yaml`` (under ``data.mode``)."""
    if mode not in VALID_DATA_MODES:
        raise ValueError(f"unknown data mode: {mode}")
    data = _read_settings_yaml()
    section = data.get("data")
    if not isinstance(section, dict):
        section = {}
    section["mode"] = mode
    data["data"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return mode


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #
def read_provider_settings() -> ProviderSettings:
    """Current provider + per-key presence (file .env *or* live process env)."""
    env = _read_env_file()
    keys_present = {
        field: bool(env.get(var) or os.environ.get(var)) for field, var in PROVIDER_KEYS.items()
    }
    return ProviderSettings(read_provider(), keys_present, VALID_PROVIDERS)


def write_provider_settings(provider: str, secrets: dict[str, str | None]) -> ProviderSettings:
    """Persist the provider choice and any supplied secrets.

    A secret that is ``None`` or empty is left untouched (so the UI can submit
    blank fields to keep an existing key). New secrets are also pushed into
    ``os.environ`` so they take effect for the running process immediately.
    """
    if provider not in VALID_PROVIDERS:
        raise UnknownProviderError(provider)

    # 1. provider -> settings.yaml (merge under data.provider, keep other keys)
    data = _read_settings_yaml()
    section = data.get("data")
    if not isinstance(section, dict):
        section = {}
    section["provider"] = provider
    data["data"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    # 2. secrets -> .env (merge), and into the live process environment
    env = _read_env_file()
    for field, value in secrets.items():
        if field not in PROVIDER_KEYS or value is None or value == "":
            continue
        var = PROVIDER_KEYS[field]
        env[var] = value
        os.environ[var] = value
    _write_env_file(env)

    return read_provider_settings()


def clear_user_settings(*, preserve_api_keys: bool = True) -> dict[str, bool]:
    """Delete the writable user settings (factory reset). Returns what was removed.

    Removes ``settings.yaml`` (the provider choice resets to the default). API-key
    secrets in ``.env`` are preserved by default; when ``preserve_api_keys`` is
    ``False`` the ``.env`` file is removed and the provider vars are dropped from the
    live process environment too. Never raises on a missing file.
    """
    removed = {"settings_yaml": False, "env": False}
    settings_path = _settings_path()
    if settings_path.is_file():
        settings_path.unlink()
        removed["settings_yaml"] = True
    if not preserve_api_keys:
        env_path = _env_path()
        if env_path.is_file():
            env_path.unlink()
            removed["env"] = True
        for var in PROVIDER_KEYS.values():
            os.environ.pop(var, None)
    return removed


def load_user_env() -> None:
    """Load persisted ``.env`` secrets into the process environment at startup.

    Existing process-environment values win (``setdefault``), so an operator can
    still override a stored secret via the real environment.
    """
    for key, value in _read_env_file().items():
        os.environ.setdefault(key, value)


def build_provider(name: str | None = None) -> MarketDataProvider:
    """Construct the configured market-data provider (or an explicit ``name``).

    Alpaca/Polygon read their keys from the environment at construction; if the
    keys are missing the provider raises a clear auth error on first use.
    """
    provider = (name or read_provider()).lower()
    if provider == "alpaca":
        from momentum.data.providers.alpaca import AlpacaProvider

        return AlpacaProvider()
    if provider == "polygon":
        from momentum.data.providers.polygon import PolygonProvider

        return PolygonProvider()
    from momentum.data.providers.yfinance import YahooProvider

    return YahooProvider()
